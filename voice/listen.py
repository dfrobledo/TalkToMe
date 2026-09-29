"""Rachel listens: hold a key, speak, and it goes to Claude Code as a typed prompt.

    hold the key ─► Rachel stops talking, the microphone records
    release it   ─► Scribe (ElevenLabs) turns the audio into text
                 ─► typed into the window that had the focus, plus Enter

The prompt reaches Claude Code exactly as if typed, so its hooks apply:
"repite" and "detalle" are handled by Rachel without spending a turn.
Only "calla" is handled here: pressing the key already silenced her.
"""
import os
import time

from . import hooks, mic, player, stt
from .config import STATE_DIR
from .tts import TTSError

PID_FILE = STATE_DIR / "listen.pid"
# The last dictation, kept to re-check what Scribe heard: talktome oye <file>.
LAST_AUDIO = STATE_DIR / "dictado.wav"
POLL = 0.02


class Listener:
    """One hold-to-talk dictation after another. `desk` is the desktop (mic.Desk)."""

    def __init__(self, cfg, desk, transcribe=stt.transcribe, clock=time.monotonic, sleep=time.sleep, out=print):
        self.cfg, self.desk, self.transcribe = cfg, desk, transcribe
        self.clock, self.sleep, self.out = clock, sleep, out

    def run(self):
        while True:
            while not self.desk.key_down():
                self.sleep(POLL)
            self.dictate()
            while self.desk.key_down():  # held past the time limit
                self.sleep(POLL)

    def dictate(self):
        """Record while the key is held, then deliver what was said. Returns the text typed."""
        window = self.desk.foreground()
        player.stop()  # she has the floor no more
        recorder = self.desk.recorder()
        try:
            recorder.start()
        except mic.MicError as e:
            return self._fail(str(e))
        self.desk.beep("start")
        started = self.clock()
        limit = self.cfg.get("listen_max_seconds", 120)
        while self.desk.key_down() and self.clock() - started < limit:
            self.sleep(POLL)
        seconds = self.clock() - started
        if seconds < self.cfg.get("listen_min_seconds", 0.4):
            recorder.cancel()  # a tap, not a dictation
            return ""
        try:
            audio = recorder.stop(LAST_AUDIO)
            began = self.clock()
            text = stt.clean(self.transcribe(audio, self.cfg))
        except (mic.MicError, TTSError, OSError) as e:
            return self._fail(str(e))
        took = self.clock() - began
        if not text:
            return self._fail(f"dictado de {seconds:.1f} s sin palabras")
        if hooks.is_stop(text):
            hooks.log(f"dictado: «{text}» → Rachel calla")
            self.out(f"» {text}  (Rachel calla)")
            return ""
        try:
            typed = self.desk.type_text(text, window)
        except mic.MicError as e:
            typed = False
            hooks.log(f"dictado: {e}")
        if not typed:
            self.desk.copy(text)
            self.desk.beep("error")
            hooks.log(f"dictado: la ventana cambió, texto en el portapapeles ({len(text)} car.)")
            self.out(f"» {text}  (quedó en el portapapeles)")
            return ""
        hooks.log(f"dictado: {seconds:.1f} s de voz → {len(text)} car. en {took:.1f} s")
        self.out(f"» {text}")
        return text

    def _fail(self, why):
        hooks.log(f"dictado: {why}")
        self.out(f"  ({why})")
        self.desk.beep("error")
        return ""


def running():
    """pid of the listener already running, if any: two would type everything twice."""
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        return None
    return pid if pid != os.getpid() and player._alive(pid) else None


def serve(cfg, key=None, out=print):
    """`talktome escucha`: listen until Ctrl+C."""
    key = key or cfg.get("listen_key", "F9")
    other = running()
    if other:
        raise mic.MicError(f"Ya hay una escucha activa (proceso {other}).")
    desk = mic.Desk(key)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    try:
        out(f"Rachel escucha: mantenga {key} mientras habla y suéltela para enviar. Ctrl+C para salir.")
        if not desk.exclusive:
            out(f"  Aviso: otro programa ya usa {key}; la tecla también le llegará a la ventana activa.")
        Listener(cfg, desk, out=out).run()
    except KeyboardInterrupt:
        out("Rachel deja de escuchar.")
    finally:
        desk.close()
        try:
            if int(PID_FILE.read_text()) == os.getpid():
                PID_FILE.unlink()
        except (OSError, ValueError):
            pass
