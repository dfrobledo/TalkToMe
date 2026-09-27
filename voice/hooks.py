"""Claude Code hook handlers.

Each handler runs inside the hook process and must return fast: anything
that talks to ElevenLabs is handed to a detached worker (`player.spawn`).
"""
import json
import os
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


def is_repeat(prompt):
    """Is the whole prompt just asking Rachel to say her last reply again?"""
    text = unicodedata.normalize("NFKD", (prompt or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\b(rachel|por favor|porfa|porfavor)\b", " ", text)
    return " ".join(text.split()) in REPEAT_WORDS


def handle(event, payload, cfg):
    """Entry point for `talktome.py hook <event>`; never blocks on audio.

    Returns a hook decision for Claude Code, if any, to print as JSON.
    """
    if event == "prompt":
        if is_repeat(payload.get("prompt") or payload.get("prompt_text")):
            player.stop()
            player.spawn("_repeat")
            # Blocked prompts never reach Claude: no turn, no tokens.
            return {"decision": "block", "reason": "Rachel repite su última respuesta."}
        if cfg.get("interrupt_on_prompt", True):
            player.stop()
        return None
    if os.environ.get("TALKTOME_DISABLE") or not cfg.get("enabled", True):
        return
    if cfg.get("muted") or not cfg.get("api_key"):
        return
    if event == "session" and cfg.get("greet_on_start") and payload.get("source", "startup") == "startup":
        _enqueue("say", {"text": persona.greeting(cfg["honorific"])})
    elif event == "notification" and cfg.get("speak_notifications"):
        line = persona.notification(payload, cfg["honorific"])
        if line:
            _enqueue("say", {"text": line})
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
    # Claim first: if the user types while a summary is being written, the
    # prompt hook interrupts this worker before it says something stale.
    player.claim()
    try:
        if kind == "say":
            text = payload["text"]
        else:
            text = compose_reply(_reply_from(payload), cfg, summarize=summarizer.summarize)
        if not text:
            return
        player.speak(text, cfg, keep=kind == "reply")
    finally:
        player.release()
