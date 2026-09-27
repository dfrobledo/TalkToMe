"""Claude Code hook handlers.

Each handler runs inside the hook process and must return fast: anything
that talks to ElevenLabs is handed to a detached worker (`player.spawn`).
"""
import json
import os
import time

from . import persona, player, speakable, transcript
from .config import STATE_DIR


def compose_reply(markdown, cfg):
    """Decide what Rachel says about a reply, given the configured mode."""
    keep_tags = cfg["model_id"] == "eleven_v3"
    h = cfg["honorific"]
    full = speakable.to_speech(markdown, keep_tags=keep_tags)
    if not full:
        return ""
    mode = cfg.get("mode", "auto")
    if mode == "full" or (mode == "auto" and len(full) <= cfg["max_chars"]):
        text, cut = speakable.truncate(full, cfg["max_chars"])
        return f"{text} {persona.more_on_screen(h)}" if cut else text
    text = speakable.lead(markdown, keep_tags=keep_tags) or full
    text, _ = speakable.truncate(text, cfg["max_chars"])
    return text if text == full else f"{text} {persona.more_on_screen(h)}"


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


def handle(event, payload, cfg):
    """Entry point for `talktome.py hook <event>`; never blocks on audio."""
    if event == "prompt":
        if cfg.get("interrupt_on_prompt", True):
            player.stop()
        return
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
    text = payload["text"] if kind == "say" else compose_reply(_reply_from(payload), cfg)
    if not text:
        return
    player.claim()
    try:
        player.speak(text, cfg)
    finally:
        player.release()
