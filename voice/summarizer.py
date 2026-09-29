"""Backup summarizer: when a reply has no spoken summary, ask Claude for one.

Runs Claude Code headless (`claude -p`) on the user's own plan. Sonnet at
low effort measured faster and more faithful to the facts than Haiku. It only kicks in for replies that did not open with a summary, so the
usual path stays instant and free. The same channel narrates the detail on
demand and, now and then, invents new idle lines for Rachel.
"""
import os
import shutil
import subprocess

from .config import STATE_DIR
from .player import NO_WINDOW

SYSTEM = "Redactas resúmenes hablados en español latinoamericano. Sigue exactamente las instrucciones del mensaje."
# Newer flags keep the run lean and out of the user's history; older CLIs
# that reject them are retried without.
# No hooks at all in the summarizer's session: neither ours (TALKTOME_DISABLE
# also guards those) nor any other the user has, which only add delay.
LEAN_FLAGS = ["--effort", "low", "--tools", "", "--no-session-persistence",
              "--disable-slash-commands", "--settings", '{"disableAllHooks": true}',
              "--system-prompt", SYSTEM]

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


NARRATION = """Eres Rachel, la asistente de voz del usuario, a quien llamas "{h}". Abajo está la última respuesta que su asistente de programación le dejó en pantalla. El usuario ya escuchó este resumen:

"{spoken}"

Ahora te pide el detalle. Escribe la lectura en voz alta del RESTO de la respuesta, para que la entienda completa sin mirar la pantalla.

Reglas:
1. No resumas: conserva cada decisión, dato, paso, opción, riesgo y pregunta, en el orden de la respuesta.
2. No repitas lo que ya dijo el resumen; si algo ya se dijo, pasa directo a lo nuevo.
3. Tablas: dilas como frases ("con ciento veinticinco kilohercios, cada trama ocupa ochenta y dos milisegundos..."). Código: di en una frase qué hace, nunca lo leas. Listas: "primero..., segundo...".
4. Pines, rutas, puertos, nombres de archivo e identificadores: nómbralos por lo que son; di el valor solo si el usuario lo necesita para actuar ("el puerto COM siete").
5. Números en palabras y copiados tal cual de la respuesta, sin combinarlos con condiciones que no son suyas.
6. Lo que sea hipótesis, dilo en palabras ("en teoría, hasta que lo midamos").
7. Habla en primera persona, como quien escribió la respuesta: "le recuerdo", "propongo", "necesito". Nunca "le recuerda", "el asistente dice" ni "la respuesta explica".
8. Español latinoamericano neutro, trato de usted, pretérito simple; tono de Rachel, sereno y claro, sin bromas que quiten espacio.
9. Prosa para el oído, en párrafos cortos, máximo {max_chars} caracteres: si no cabe todo, abrevia lo menos importante, nunca el final ni las preguntas. Sin markdown, listas, comillas ni emojis.

Responde SOLO con esa lectura.

--- RESPUESTA EN PANTALLA ---
{reply}
--- FIN ---"""


def _ask_claude(prompt, cfg):
    """Run `prompt` through headless Claude Code; "" if it could not answer."""
    if cfg.get("summarizer", "claude") != "claude":
        return ""
    base = list(cfg.get("summarizer_command") or ["claude", "-p", "--model", "sonnet"])
    exe = shutil.which(base[0])
    if not exe:
        _log(f"no encuentro '{base[0]}' en el PATH")
        return ""
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


def summarize(reply, cfg):
    """Spoken summary of `reply`, or "" if Claude could not be reached."""
    return _ask_claude(INSTRUCTIONS.format(
        h=cfg["honorific"], max_chars=cfg.get("summary_max_chars", 650), reply=reply[:20000]
    ), cfg)


def narrate(reply, spoken, cfg):
    """Everything in `reply` beyond the summary already `spoken`, for the ear."""
    return _ask_claude(NARRATION.format(
        h=cfg["honorific"], spoken=spoken or "(ninguno)",
        # Ask for less than the hard cap: the model overshoots, and the cut
        # would fall on the end, where the questions usually are.
        max_chars=int(cfg.get("detail_max_chars", 2500) * 0.8), reply=reply[:20000],
    ), cfg)


INVENTION = """Escribes frases para Rachel, la replicante de Blade Runner que hoy es la asistente de voz del usuario, a quien llama "{h}". Rachel las dice en voz alta cuando el usuario lleva un rato sin responderle: le recuerda, con estilo, que sigue ahí esperando.

Escribe {count} frases NUEVAS. Reglas:
1. Cada frase se apoya en el universo Blade Runner: la película de 1982, Blade Runner 2049, los cortos (2022, 2036, 2048) o la novela de Philip K. Dick. Personajes, lugares, objetos, pruebas, recuerdos; reinterpretados con ingenio, nunca citas literales largas.
2. Varía las referencias entre frases y aléjate de las que ya existen (abajo). Sorprende: busca rincones menos obvios de ese universo.
3. Tono de Rachel: serena, elegante, con humor seco o melancolía noir. Nunca grosera ni amenazante.
4. Español latinoamericano neutro, trato de usted, sin voseo ni "vosotros".
5. Cada frase incluye exactamente una vez el marcador {{h}} donde va el trato ("Sigo aquí, {{h}}."). Nada de otras llaves.
6. Máximo {max_chars} caracteres por frase. Sin markdown, emojis, comillas ni numeración.

Responde SOLO con las {count} frases, una por línea.

--- FRASES QUE YA EXISTEN ---
{known}
--- FIN ---"""


def invent_lines(known, cfg, count=3):
    """New idle lines from Claude, one per line with a literal {h}; "" on failure."""
    return _ask_claude(INVENTION.format(
        h=cfg["honorific"], count=count, max_chars=120, known="\n".join(known),
    ), cfg)
