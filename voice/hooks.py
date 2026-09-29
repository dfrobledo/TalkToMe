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

from . import companion, persona, player, projects, speakable, summarizer, transcript
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


STOP_WORDS = {
    "calla", "callate", "callese", "silencio", "guarda silencio", "basta", "ya basta",
    "alto", "detente", "suficiente", "shh", "shhh",
}


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


def is_stop(prompt):
    """Is the whole prompt just asking Rachel to be quiet?"""
    return _command(prompt) in STOP_WORDS


def is_detail(prompt):
    """Is the whole prompt just asking Rachel for the rest of her last reply?"""
    return _command(prompt) in DETAIL_WORDS


# What `talktome escucha` just typed: its prompt is a turn started by voice.
DICTATED = STATE_DIR / "dictated.json"


def mark_dictated(text):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DICTATED.write_text(json.dumps({"text": text, "at": time.time()}, ensure_ascii=False), encoding="utf-8")


def was_dictated(prompt, within=30):
    """Did this prompt come from the dictation, just now? Asking forgets it."""
    try:
        mark = json.loads(DICTATED.read_text(encoding="utf-8"))
        DICTATED.unlink()
    except (OSError, ValueError):
        return False
    return time.time() - mark.get("at", 0) < within and _command(mark.get("text")) == _command(prompt)


def narrates(cfg, voice):
    """Keep the user company during this turn? `narrate_progress`: voice, always or off."""
    mode = cfg.get("narrate_progress", "voice")
    ready = cfg.get("enabled", True) and not cfg.get("muted") and cfg.get("api_key")
    return bool(ready) and (mode == "always" or (mode == "voice" and voice))


def handle(event, payload, cfg):
    """Entry point for `talktome.py hook <event>`; never blocks on audio.

    Returns a hook decision for Claude Code, if any, to print as JSON.
    """
    # Set inside the summarizer's own Claude session: its prompt must not
    # silence the worker that is waiting for that very summary.
    if os.environ.get("TALKTOME_DISABLE"):
        return None
    # Each terminal is its own session: typing in one only silences what
    # that one was saying, and "repite" repeats its own last reply.
    session = payload.get("session_id") or ""
    track(event, session)
    if event == "end":
        return None
    if event == "prompt":
        prompt = payload.get("prompt") or payload.get("prompt_text")
        if is_detail(prompt):
            player.stop(session)
            player.spawn("_detail", session, payload.get("cwd") or "")
            return {"decision": "block", "reason": "Rachel le lee el detalle de su última respuesta."}
        if is_stop(prompt):
            player.stop(session)
            return {"decision": "block", "reason": "Rachel guarda silencio."}
        if is_repeat(prompt):
            player.stop(session)
            player.spawn("_repeat", session, payload.get("cwd") or "")
            # Blocked prompts never reach Claude: no turn, no tokens.
            return {"decision": "block", "reason": "Rachel repite su última respuesta."}
        if cfg.get("interrupt_on_prompt", True):
            player.stop(session)
        if LISTEN_DOZED.exists():
            # It left after hours without activity, the terminal stayed open.
            LISTEN_DOZED.unlink(missing_ok=True)
            start_listening()
        folder = player.session_dir(session)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "prompt-at").write_text(str(time.time()), encoding="utf-8")
        companion.turn_done(session).unlink(missing_ok=True)
        if narrates(cfg, was_dictated(prompt)) and payload.get("transcript_path"):
            player.spawn("_acompana", session, payload["transcript_path"])
        return None
    if event == "stop":
        # The companion stops here; the reply takes over.
        folder = player.session_dir(session)
        folder.mkdir(parents=True, exist_ok=True)
        companion.turn_done(session).write_text(str(time.time()), encoding="utf-8")
        payload = {**payload, "stop_at": time.time()}
    if not cfg.get("enabled", True):
        return
    if event == "session" and cfg.get("listen_on_start", True) and cfg.get("api_key"):
        start_listening()
    if cfg.get("muted") or not cfg.get("api_key"):
        return
    where = {"session_id": session, "cwd": payload.get("cwd") or ""}
    project, cfg = projects.identify(where["cwd"], cfg)
    if event == "session" and cfg.get("greet_on_start") and payload.get("source", "startup") == "startup":
        named = project if announces(cfg) else ""
        # The greeting already names the project: no callsign on top.
        _enqueue("say", {"text": persona.greeting(cfg["honorific"], project=named), "polite": True,
                         "callsign": False, **where})
    elif event == "notification" and cfg.get("speak_notifications"):
        line = persona.notification(payload, cfg["honorific"])
        if line:
            # Notifications never cut a reply short: they wait their turn,
            # and the idle reminder is dropped if Rachel is already talking.
            idle = persona.is_idle(payload)
            # Now and then, after an idle reminder, Claude writes new ones.
            invent = idle and random.random() < cfg.get("invent_chance", 0.2)
            _enqueue("say", {"text": line, "polite": True, "skip_if_busy": idle, "invent": invent, **where})
    elif event == "stop":
        _enqueue("reply", payload)


# Claude Code sessions that are open: SessionStart adds, SessionEnd removes.
# The background listener leaves when none is left.
OPEN_SESSIONS = STATE_DIR / "open-sessions"
ACTIVITY = STATE_DIR / "claude-activity"
# Left by a background listener that quit for lack of activity: the next
# prompt brings it back.
LISTEN_DOZED = STATE_DIR / "listen-dozed"


def track(event, session):
    """Note that Claude Code is in use, and which sessions are open."""
    OPEN_SESSIONS.mkdir(parents=True, exist_ok=True)
    ACTIVITY.write_text(str(time.time()), encoding="utf-8")
    if not session:
        return
    marker = OPEN_SESSIONS / re.sub(r"[^\w-]", "", session)[:80]
    if event == "end":
        marker.unlink(missing_ok=True)
    elif event == "session" or marker.exists():
        marker.touch()


def claude_open(idle_minutes=120, grace=60, now=None):
    """Is Claude Code still in use? False once every session ended (after `grace`
    seconds, in case one reopens) or nothing happened for `idle_minutes`."""
    now = now or time.time()
    try:
        last = ACTIVITY.stat().st_mtime
    except OSError:
        return False
    if now - last > idle_minutes * 60:
        return False  # terminals closed without saying goodbye
    try:
        if any(OPEN_SESSIONS.iterdir()):
            return True
    except OSError:
        pass
    return now - last < grace


def start_listening():
    """Launch `escucha` in the background if it is not running (Windows only)."""
    from . import listen, mic

    if mic.available() and not listen.running():
        player.spawn("escucha", "--fondo")


def announces(cfg):
    return cfg.get("announce_project", "switch") in ("switch", "always")


def _callsign(project, cfg):
    """The `intro` for `player.speak`: name the project when the voice changes project."""
    def intro(previous):
        mode = cfg.get("announce_project", "switch")
        if not project or not announces(cfg):
            return ""
        # Nothing heard before (or only a console command): no need to say where.
        if mode == "always" or (previous and previous != project):
            return persona.callsign(project, cfg["honorific"])
        return ""

    return intro


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
    session = payload.get("session_id") or ""
    project, cfg = projects.identify(payload.get("cwd"), cfg)
    player.remember_project(session, project)
    if payload.get("polite") and player.busy():
        if payload.get("skip_if_busy") or not player.wait_turn(timeout=180):
            log("aviso omitido: Rachel estaba hablando")
            return
    reply = _reply_from(payload) if kind == "reply" else ""
    if kind == "reply" and not reply.strip():
        log("respuesta vacía: nada que decir")  # and nothing to interrupt for
        return
    if kind == "reply":
        player.keep_markdown(session, reply)  # for "detalle"
    # Claim before summarizing: if the user types in this terminal while a
    # summary is being written, the prompt hook interrupts this worker
    # before it says something stale. Other terminals are not affected.
    player.claim(session)
    try:
        if kind == "say":
            text = payload["text"]
        else:
            text = compose_reply(reply, cfg, summarize=_logged(summarizer.summarize))
            where = f" [{project}]" if project else ""
            log(f"respuesta{where}: {len(reply)} car. en pantalla → {len(text)} car. hablados")
        if not text:
            return
        intro = _callsign(project, cfg) if payload.get("callsign", True) else None
        # If another project is talking, wait for it to finish instead of
        # cutting it off; the idle reminder does not wait at all.
        wait = 0 if payload.get("skip_if_busy") else 180 if payload.get("polite") else 300
        player.first_sound = None
        if not player.speak(text, cfg, keep=kind == "reply", session=session, intro=intro, wait=wait):
            log(f"{'respuesta' if kind == 'reply' else 'aviso'} omitido: otra sesión ocupó la voz demasiado tiempo")
        elif kind == "reply":
            log(_timing(session, payload.get("stop_at"), player.first_sound))
    finally:
        player.release(session)
    if payload.get("invent"):
        added = persona.invent(cfg)
        log(f"frases nuevas de Rachel: {len(added)}" + "".join(f" | {line}" for line in added))


def _timing(session, stop_at, first_sound):
    """How long the turn took, from the prompt to Claude's last word to Rachel's first."""
    parts = []
    try:
        prompt_at = float((player.session_dir(session) / "prompt-at").read_text())
    except (OSError, ValueError):
        prompt_at = None
    if prompt_at and stop_at:
        parts.append(f"Claude {stop_at - prompt_at:.1f} s")
    if stop_at and first_sound:
        parts.append(f"voz {first_sound - stop_at:.1f} s después")
    return "tiempos: " + (" · ".join(parts) or "sin datos")


def detail(cfg, session=None):
    """Narrate the rest of the session's last reply, beyond the summary already heard."""
    h = cfg["honorific"]
    reply = player.last_markdown(session)
    player.claim(session)
    try:
        if not reply.strip():
            player.speak(persona.nothing_to_detail(h), cfg, session=session)
            return
        # Narrating takes a few seconds; say so instead of going quiet.
        player.speak(persona.one_moment(h), cfg, session=session)
        started = time.monotonic()
        spoken = player.last_spoken(session)
        text = speakable.to_speech(summarizer.narrate(reply, spoken, cfg)).replace("\n\n", " ")
        if text:
            log(f"detalle narrado en {time.monotonic() - started:.1f} s → {len(text)} car.")
        else:
            text = speakable.to_speech(reply).replace("\n\n", " ")
            log("detalle: el narrador falló, leo la respuesta limpia")
        text, _ = speakable.truncate(text, cfg.get("detail_max_chars", 2500))
        player.speak(text, cfg, session=session)
    finally:
        player.release(session)


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
