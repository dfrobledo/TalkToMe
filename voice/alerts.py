"""Rachel reports what went wrong, out loud, instead of failing in silence.

Most of TalkToMe runs without a console (hook workers, the background
listener), so an error nobody sees might as well not exist. Here each
failure is sorted into a kind with a short, in-character line that says
what to do about it.

When the failure is ElevenLabs itself (bad key, no credits, no network) her
own voice is out of reach, so the operating system's offline voice says it
instead. Each kind waits a while before being reported again, so one
problem never turns into a litany.
"""
import json
import os
import shutil
import subprocess
import sys
import time

from . import player
from .config import STATE_DIR

STATE_FILE = STATE_DIR / "alerts.json"
# Each one names the component to check first, then what to do. Short, so
# they are synthesized in her voice ahead of time (`warm`) and still sound
# like her when ElevenLabs itself is the one failing.
LINES = {
    "auth": "Falla en ElevenLabs, {h}: la clave no es válida. Revise el archivo punto env de TalkToMe.",
    "quota": "Falla en ElevenLabs, {h}: se acabaron los créditos. Revise su plan en la página de ElevenLabs.",
    "no_key": "Falta configuración, {h}: no hay clave de ElevenLabs. Póngala en el archivo punto env.",
    "network": "Falla de red, {h}: no llego a ElevenLabs. Revise su conexión a internet.",
    "mic": "Falla en el micrófono, {h}. Revise que esté conectado y permitido en la privacidad de Windows.",
    "elevated": "Falla al escribir, {h}: la terminal corre como administrador. Ábrala sin permisos elevados.",
    "stt": "Falla en Scribe, {h}: no pude transcribir lo que dijo. El detalle está en el registro.",
    "realtime": "Scribe en tiempo real no responde, {h}. Sigo con el modo normal, un poco más lento.",
    "listen": "Falla en la escucha, {h}: no pude tomar la tecla del dictado. Corra talktome doctor.",
    "summarizer": "Falla en el resumidor, {h}: Claude por consola no responde. Revise que claude esté en el PATH.",
    "player": "Falla en el audio, {h}: no encuentro el reproductor. Instale mpv.",
    "clipboard": "Cambió de ventana, {h}. Le dejé el texto en el portapapeles.",
    "focus": "Falla al traer la terminal, {h}: Windows no me dejó ponerla al frente. El texto está en el portapapeles.",
    "no_target": "Falta la terminal, {h}: no encuentro una sesión de Claude Code abierta. El texto está en el portapapeles.",
    "wake": "Falla en la activación por voz, {h}: no pude cargar Vosk o su modelo. Corra talktome despierta.",
    "crash": "Falla interna de TalkToMe, {h}. El detalle está en el registro, talktome punto log.",
}
# Seconds before the same kind is said again.
COOLDOWN = {"realtime": 6 * 3600, "summarizer": 3600, "clipboard": 0}
DEFAULT_COOLDOWN = 10 * 60
# ElevenLabs cannot synthesize these right now: only her cached voice, or
# the system's, can say them.
OFFLINE = {"auth", "quota", "network", "no_key"}


def classify(error):
    """The kind of a failure, from the exception (or its message)."""
    text = str(error).lower()
    if "no hay reproductor" in text:
        return "player"
    if "quota" in text or "credits" in text:
        return "quota"
    if "falta elevenlabs_api_key" in text or "texto de ejemplo" in text:
        return "no_key"
    if "401" in text or "auth_error" in text or "invalid_api_key" in text or "unauthorized" in text:
        return "auth"
    if "administrador" in text:
        return "elevated"
    if "micrófono" in text:
        return "mic"
    if isinstance(error, OSError) or any(word in text for word in (
            "sin conexión", "timed out", "getaddrinfo", "connection", "sin red", "no respondió")):
        return "network"
    return "crash"


def due(kind, now=None):
    """Is it time to say this kind again? Marks it said when it is."""
    now = now or time.time()
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if now - state.get(kind, 0) < COOLDOWN.get(kind, DEFAULT_COOLDOWN):
        return False
    state[kind] = now
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass
    return True


def line(kind, cfg):
    h = cfg.get("honorific", "señor")
    return LINES.get(kind, LINES["crash"]).format(h=h, H=h.capitalize())


def report(kind, cfg, detail=""):
    """Say what went wrong (if reporting is on and it was not said a moment ago).

    Never raises: reporting an error must not become another one.
    """
    try:
        from . import hooks

        hooks.log(f"aviso de error [{kind}]: {detail}" if detail else f"aviso de error [{kind}]")
        if not cfg.get("report_errors", True) or cfg.get("muted") or not cfg.get("enabled", True):
            return False
        if os.environ.get("TALKTOME_DISABLE") or not due(kind):
            return False
        text = line(kind, cfg)
        offline = kind in OFFLINE or kind == "player" or not cfg.get("api_key")
        if offline and (kind == "player" or not player.cached(text, cfg)):
            return system_say(text)
        # Her own voice, from a worker (from the cache when ElevenLabs is
        # down). If that fails too, the worker's error lands here again as
        # an ElevenLabs kind, and the cooldown keeps it from looping.
        hooks._enqueue("say", {"text": text, "polite": True, "callsign": False})
        return True
    except Exception:
        return False


def missing(cfg, extra=()):
    """Alert lines (and `extra` lines) not yet in the cache in the current voice."""
    texts = [line(kind, cfg) for kind in LINES] + list(extra)
    return [text for text in dict.fromkeys(texts) if not player.cached(text, cfg)]


def warm(cfg, extra=()):
    """Synthesize every alert line (and `extra`) into the cache while ElevenLabs works.

    A one-time cost of a few thousand characters per voice; afterwards they
    play at once and need no network. Returns how many were made.
    """
    made = 0
    for text in missing(cfg, extra):
        player.prefetch(text, cfg)
        made += 1
    return made


def system_say(text):
    """The operating system's own voice, offline. False if there is none."""
    env = {**os.environ, "TALKTOME_SAY": text}
    if sys.platform == "win32":
        # Text through the environment: no quoting to get wrong. A Spanish
        # voice if Windows has one installed.
        script = ("Add-Type -AssemblyName System.Speech; "
                  "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'es*' } "
                  "| Select-Object -First 1; "
                  "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; $s.Speak($env:TALKTOME_SAY)")
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    elif sys.platform == "darwin":
        cmd = ["say", text]
    elif shutil.which("spd-say"):
        cmd = ["spd-say", "-l", "es", text]
    elif shutil.which("espeak-ng") or shutil.which("espeak"):
        cmd = [shutil.which("espeak-ng") or "espeak", "-v", "es", text]
    else:
        return False
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags)
        return True
    except OSError:
        return False
