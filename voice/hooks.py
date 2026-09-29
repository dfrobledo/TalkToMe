"""Claude Code hook handlers.

Each handler runs inside the hook process and must return fast: anything
that talks to ElevenLabs is handed to a detached worker (`player.spawn`).
"""
import json
import os
import random
import re
import time
import unicodedata

from . import persona, player, speakable, summarizer, transcript
from .config import STATE_DIR


def compose_reply(markdown, cfg, summarize=None):
    """Decide what Rachel says about a reply, given the configured mode.

    Order of preference: the whole reply if it is short, the spoken summary
    Claude wrote at the top, a summary made on the spot by `summarize`
    (layer 2), and as a last resort a plain heads-up.
    """
    keep_tags = cfg["model_id"] == "eleven_v3"
    h = cfg["honorific"]
    full = speakable.to_speech(markdown, keep_tags=keep_tags)
    if not full:
        return ""
    mode = cfg.get("mode", "auto")
    if mode == "full" or (mode == "auto" and len(full) <= cfg["max_chars"]):
        text, cut = speakable.truncate(full, cfg["max_chars"])
        return f"{text} {persona.more_on_screen(h)}" if cut else text

    limit = cfg.get("summary_max_chars", cfg["max_chars"])
    opening = speakable.spoken_summary(markdown, keep_tags=keep_tags)
    waiting = speakable.needs_input(markdown)
    # A real summary carries the question the reply ends with; an opening
    # paragraph that misses it is just the start of the answer.
    text = opening if opening and (speakable.asks(opening) or not waiting) else ""
    if not text and summarize:
        text = speakable.to_speech(summarize(markdown, cfg), keep_tags=keep_tags).replace("\n\n", " ")
    if text:
        text, _ = speakable.truncate(text, limit)
        return text if text == full else f"{text} {persona.more_on_screen(h)}"
    if waiting:
        if opening:
            opening, _ = speakable.truncate(opening, limit)
            return f"{opening} {persona.needs_answer(h)}"
        return persona.needs_answer(h)
    return persona.done(h)


def _reply_from(payload):
    # Newer Claude Code versions hand over the reply directly.
    text = payload.get("last_assistant_message")
    if isinstance(text, str) and text.strip():
        return text
    path = payload.get("transcript_path")
    # The transcript can lag a moment behind the Stop event.
    for _ in range(6):
        text = transcript.final_reply(path) if path else ""
        if text:
            return text
        time.sleep(0.25)
    return ""


def _enqueue(kind, payload):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"payload-{kind}-{time.time_ns()}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    player.spawn("_speak", kind, str(path))


REPEAT_WORDS = {
    "repite", "repitelo", "repitemelo", "repiteme", "repite eso", "repitelo todo", "repetir",
    "otra vez", "de nuevo", "que dijiste", "no te escuche", "no te oi",
}


DETAIL_WORDS = {
    "detalle", "el detalle", "detalles", "los detalles", "mas detalle", "con detalle",
    "dame el detalle", "dime el detalle", "leeme el detalle", "lee el detalle", "cuentame el detalle",
    "leelo todo", "lee todo", "leemelo todo", "dimelo todo", "todo", "completo", "la respuesta completa",
}
LAST_REPLY_MD = STATE_DIR / "last-reply.md"


def _command(prompt):
    """The prompt reduced to bare words: no accents, punctuation, name or courtesy."""
    text = unicodedata.normalize("NFKD", (prompt or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\b(rachel|por favor|porfa|porfavor)\b", " ", text)
    return " ".join(text.split())


def is_repeat(prompt):
    """Is the whole prompt just asking Rachel to say her last reply again?"""
    return _command(prompt) in REPEAT_WORDS


def is_detail(prompt):
    """Is the whole prompt just asking Rachel for the rest of her last reply?"""
    return _command(prompt) in DETAIL_WORDS


def handle(event, payload, cfg):
    """Entry point for `talktome.py hook <event>`; never blocks on audio.

    Returns a hook decision for Claude Code, if any, to print as JSON.
    """
    # Set inside the summarizer's own Claude session: its prompt must not
    # silence the worker that is waiting for that very summary.
    if os.environ.get("TALKTOME_DISABLE"):
        return None
    if event == "prompt":
        prompt = payload.get("prompt") or payload.get("prompt_text")
        if is_detail(prompt):
            player.stop()
            player.spawn("_detail")
            return {"decision": "block", "reason": "Rachel le lee el detalle de su última respuesta."}
        if is_repeat(prompt):
            player.stop()
            player.spawn("_repeat")
            # Blocked prompts never reach Claude: no turn, no tokens.
            return {"decision": "block", "reason": "Rachel repite su última respuesta."}
        if cfg.get("interrupt_on_prompt", True):
            player.stop()
        return None
    if not cfg.get("enabled", True):
        return
    if cfg.get("muted") or not cfg.get("api_key"):
        return
    if event == "session" and cfg.get("greet_on_start") and payload.get("source", "startup") == "startup":
        _enqueue("say", {"text": persona.greeting(cfg["honorific"]), "polite": True})
    elif event == "notification" and cfg.get("speak_notifications"):
        line = persona.notification(payload, cfg["honorific"])
        if line:
            # Notifications never cut a reply short: they wait their turn,
            # and the idle reminder is dropped if Rachel is already talking.
            idle = persona.is_idle(payload)
            # Now and then, after an idle reminder, Claude writes new ones.
            invent = idle and random.random() < cfg.get("invent_chance", 0.2)
            _enqueue("say", {"text": line, "polite": True, "skip_if_busy": idle, "invent": invent})
    elif event == "stop":
        _enqueue("reply", payload)


def work(kind, payload_file, cfg):
    """Detached worker: build the line and speak it."""
    try:
        with open(payload_file, encoding="utf-8") as f:
            payload = json.load(f)
    finally:
        try:
            os.remove(payload_file)
        except OSError:
            pass
    if payload.get("polite") and player.busy():
        if payload.get("skip_if_busy") or not player.wait_turn(timeout=180):
            log("aviso omitido: Rachel estaba hablando")
            return
    reply = _reply_from(payload) if kind == "reply" else ""
    if kind == "reply" and not reply.strip():
        log("respuesta vacía: nada que decir")  # and nothing to interrupt for
        return
    if kind == "reply":
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_REPLY_MD.write_text(reply, encoding="utf-8")  # for "detalle"
    # Claim before summarizing: if the user types while a summary is being
    # written, the prompt hook interrupts this worker before it says
    # something stale.
    player.claim()
    try:
        if kind == "say":
            text = payload["text"]
        else:
            text = compose_reply(reply, cfg, summarize=_logged(summarizer.summarize))
            log(f"respuesta: {len(reply)} car. en pantalla → {len(text)} car. hablados")
        if not text:
            return
        player.speak(text, cfg, keep=kind == "reply")
    finally:
        player.release()
    if payload.get("invent"):
        added = persona.invent(cfg)
        log(f"frases nuevas de Rachel: {len(added)}" + "".join(f" | {line}" for line in added))


def detail(cfg):
    """Narrate the rest of the last reply, beyond the summary already heard."""
    h = cfg["honorific"]
    try:
        reply = LAST_REPLY_MD.read_text(encoding="utf-8")
    except OSError:
        reply = ""
    player.claim()
    try:
        if not reply.strip():
            player.speak(persona.nothing_to_detail(h), cfg)
            return
        # Narrating takes a few seconds; say so instead of going quiet.
        player.speak(persona.one_moment(h), cfg)
        started = time.monotonic()
        text = speakable.to_speech(summarizer.narrate(reply, player.last_spoken(), cfg)).replace("\n\n", " ")
        if text:
            log(f"detalle narrado en {time.monotonic() - started:.1f} s → {len(text)} car.")
        else:
            text = speakable.to_speech(reply).replace("\n\n", " ")
            log("detalle: el narrador falló, leo la respuesta limpia")
        text, _ = speakable.truncate(text, cfg.get("detail_max_chars", 2500))
        player.speak(text, cfg)
    finally:
        player.release()


def _logged(summarize):
    def run(reply, cfg):
        started = time.monotonic()
        text = summarize(reply, cfg)
        log(f"sin resumen propio → resumidor {'OK' if text else 'FALLÓ'} en {time.monotonic() - started:.1f} s")
        return text

    return run


def log(message):
    """One line per decision in ~/.talktome/talktome.log, to explain silences."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / "talktome.log"
    if path.exists() and path.stat().st_size > 512_000:
        path.replace(path.with_suffix(".log.old"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
