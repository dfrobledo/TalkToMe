"""Backup summarizer: when a reply has no spoken summary, ask Claude for one.

Runs Claude Code headless (`claude -p`) on the user's own plan. Sonnet at
low effort measured faster and more faithful to the facts than Haiku. It only kicks in for replies that did not open with a summary, so the
usual path stays instant and free.
"""
import os
import shutil
import subprocess

from .config import STATE_DIR
from .player import NO_WINDOW

SYSTEM = "Redactas resúmenes hablados en español latinoamericano. Sigue exactamente las instrucciones del mensaje."
# Newer flags keep the run lean and out of the user's history; older CLIs
# that reject them are retried without.
LEAN_FLAGS = ["--effort", "low", "--tools", "", "--no-session-persistence",
              "--disable-slash-commands", "--system-prompt", SYSTEM]

INSTRUCTIONS = """Eres Rachel, la asistente de voz del usuario, a quien llamas "{h}". Abajo está la última respuesta que su asistente de programación le dejó en pantalla. Escribe el resumen hablado que Rachel le dirá en voz alta, para que quede enterado de lo importante sin mirar la pantalla.

Reglas:
1. Si la respuesta le pide algo al usuario (una respuesta, una decisión, una acción), la PRIMERA frase es esa pregunta o pedido, dicho de forma simple.
2. Luego la conclusión y cada decisión o hallazgo relevante. Omite el contexto que el usuario ya conoce.
3. Números solo si deciden algo, dichos en palabras ("diez por segundo", "dos kilómetros"), y copiados tal cual de la respuesta: nunca combines un número con una condición distinta a la suya. Ante la duda, omite el número.
4. Sin jerga ni siglas técnicas: nada de pines, nombres de archivo, rutas, identificadores de código, modelos de chips, tablas ni anglicismos como "spike" o "HAT". Dilo en español llano ("una prueba rápida del hardware", "la radio del Raspberry Pi").
5. Lo que sea hipótesis o no esté medido, dilo en palabras ("en teoría, hasta que lo midamos").
6. Español latinoamericano neutro y trato de usted: "¿ya enciende?", "le propongo"; nunca voseo ("tenés", "conectás"), nunca "vale", "ordenador", "vosotros". Pretérito simple: "revisé", no "he revisado".
7. Tono de Rachel: sereno, cálido, con humor seco muy breve y opcional. El humor nunca le quita espacio a la información.
8. Un solo párrafo de prosa, de una a cinco frases según lo que haya que contar, máximo {max_chars} caracteres. Sin markdown, sin listas, sin comillas, sin emojis.

Responde SOLO con ese párrafo.

--- RESPUESTA EN PANTALLA ---
{reply}
--- FIN ---"""


def _log(message):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / "talktome.log", "a", encoding="utf-8") as f:
        f.write(f"resumidor: {message}\n")


def summarize(reply, cfg):
    """Spoken summary of `reply`, or "" if Claude could not be reached."""
    if cfg.get("summarizer", "claude") != "claude":
        return ""
    base = list(cfg.get("summarizer_command") or ["claude", "-p", "--model", "sonnet"])
    exe = shutil.which(base[0])
    if not exe:
        _log(f"no encuentro '{base[0]}' en el PATH")
        return ""
    prompt = INSTRUCTIONS.format(
        h=cfg["honorific"], max_chars=cfg.get("summary_max_chars", 650), reply=reply[:20000]
    )
    # Our own hooks must not fire inside the summarizer's session.
    env = {**os.environ, "TALKTOME_DISABLE": "1"}
    # A neutral folder: no project CLAUDE.md steering the output format.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for cmd in ([exe, *base[1:], *LEAN_FLAGS], [exe, *base[1:]]):
        try:
            done = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                errors="replace", env=env, cwd=STATE_DIR, creationflags=NO_WINDOW, timeout=cfg.get("summarizer_timeout", 60),
            )
        except subprocess.TimeoutExpired:
            _log("se agotó el tiempo de espera")
            return ""
        except OSError as e:
            _log(f"no pude ejecutar Claude: {e}")
            return ""
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
        _log(f"código {done.returncode}: {(done.stderr or done.stdout).strip()[:300]}")
    return ""
