"""Rachel's fixed lines: greetings, attention calls and sign-offs.

They are short and repeat often, so after the first time they are served
from the local cache and cost no ElevenLabs characters. To keep them from
getting predictable they come from shuffled decks (`deck.py`) over the
bank in `lines.py`, shaped by the time of day, how long the user has kept
Rachel waiting and the Blade Runner calendar, plus lines Claude invents now
and then.
"""
import re
from datetime import datetime

from . import deck, lines, summarizer

# Notification types worth interrupting the silence for.
ATTENTION = {"permission_prompt", "idle_prompt", "elicitation_dialog", "agent_needs_input"}


def _moment(now):
    return "night" if now.hour >= 20 or now.hour < 6 else "day"


def _fill(line, h, **extra):
    return line.format(h=h, H=h.capitalize(), **extra)


def _draw(name, bank, now, tone=None, extra=()):
    """A line from `bank` (plus `extra` lines, tone 1) fitting this moment and tone."""
    meta = {text: (level, moment) for text, level, moment in bank}
    meta.update({text: (1, None) for text in extra if text not in meta})
    moment = _moment(now)

    def fits(text):
        level, when = meta[text]
        return (tone is None or level == tone) and when in (None, moment)

    return deck.draw(name, meta, fits)


def _special(h, now):
    """The Blade Runner anniversary line, only the first time Rachel speaks that day."""
    line = lines.SPECIAL_DATES.get(now.strftime("%m-%d"))
    if line and deck.first_time_today("special", now.date().isoformat()):
        return _fill(line, h)
    return ""


def greeting(h, now=None, project=""):
    """Hello on opening a session, naming its project when there is one."""
    now = now or datetime.now()
    hour = now.hour
    salute = "Buenos días" if 5 <= hour < 12 else "Buenas tardes" if 12 <= hour < 20 else "Buenas noches"
    opening = _fill(_draw("opening", lines.SESSION_OPENINGS, now), h, p=project) + " " if project else ""
    special = _special(h, now)
    if special:
        return f"{salute}, {h}. {opening}{special}" if opening else f"{salute}. {special}"
    return f"{salute}, {h}. {opening}{_fill(_draw('greeting', lines.GREETINGS, now), h)}"


def callsign(project, h, now=None):
    """Where Rachel speaks from, said when her voice changes project."""
    return _fill(_draw("callsign", lines.CALLSIGNS, now or datetime.now()), h, p=project)


def idle(h, now=None):
    """The "still waiting for you" reminder, more theatrical the longer the wait."""
    now = now or datetime.now()
    tone = deck.waits(now.timestamp())
    special = _special(h, now)
    if special:
        return special
    return _fill(_draw("idle", lines.IDLE, now, tone=tone, extra=deck.invented()), h)


def notification(payload, h, now=None):
    """Translate Claude Code's notification into something Rachel would say.

    Returns "" for notifications that do not need the user (auth, quota...).
    """
    now = now or datetime.now()
    kind = payload.get("notification_type")
    message = payload.get("message") or ""
    if kind and kind not in ATTENTION:
        return ""
    tool = re.search(r"permission to use (.+?)\.?$", message)
    if tool:
        return _fill(_draw("permission-tool", lines.PERMISSION_TOOL, now), h, tool=tool.group(1))
    if kind == "permission_prompt" or "permission" in message.lower():
        return _fill(_draw("permission", lines.PERMISSION, now), h)
    if is_idle(payload):
        return idle(h, now)
    return _fill(_draw("attention", lines.ATTENTION, now), h)


def is_idle(payload):
    """The "still waiting for you" reminder: pointless while Rachel is talking."""
    message = (payload.get("message") or "").lower()
    return payload.get("notification_type") == "idle_prompt" or "waiting for your input" in message


def _normal(text):
    return re.sub(r"\W+", " ", text.lower()).strip()


def clean_invented(raw, h, known, max_chars):
    """The usable lines in Claude's answer: one {h} each, short, plain, new."""
    seen = {_normal(text) for text in known}
    good = []
    for line in raw.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip("\"'“”«»").strip()
        if line.count("{h}") != 1 or re.search(r"[{}*#_`<>\[\]]", line.replace("{h}", "")):
            continue
        if not 20 <= len(_fill(line, h)) <= max_chars or _normal(line) in seen:
            continue
        seen.add(_normal(line))
        good.append(line)
    return good


def invent(cfg):
    """Have Claude write a few new idle lines and add them to the deck.

    Runs in the worker after Rachel spoke, so it never delays her.
    """
    known = [text for text, _, _ in lines.IDLE] + deck.invented()
    raw = summarizer.invent_lines(known, cfg)
    max_chars = min(cfg.get("cache_max_chars", 160), 150)
    fresh = clean_invented(raw, cfg["honorific"], known, max_chars)
    return deck.add_invented(fresh, cfg.get("invented_max", 60))


def one_moment(h):
    return f"Con gusto, {h}. Deme unos segundos."


def nothing_to_detail(h):
    return f"Todavía no tengo ninguna respuesta que detallarle, {h}."


def needs_answer(h):
    return f"{h.capitalize()}, necesito que me responda algo. Está en pantalla."


def done(h):
    return f"Listo, {h}. El detalle está en pantalla."


def more_on_screen(h):
    return f"El detalle está en pantalla, {h}."


def ack(h, now=None):
    """Said the moment a dictation is sent."""
    return _fill(_draw("ack", lines.ACKS, now or datetime.now()), h)


def thinking(h, tone=1, expressive=False, now=None):
    """A thinking sound while Claude works; eleven_v3 (`expressive`) also sighs and hums."""
    bank = lines.THINKING + (lines.THINKING_V3 if expressive else [])
    return _fill(_draw("thinking", bank, now or datetime.now(), tone=tone), h)


TESTS = re.compile(r"\b(pytest|unittest|jest|vitest|mocha|tox|nox|ctest|(npm|pnpm|yarn|bun) (run )?test|"
                   r"(cargo|go|dotnet|mvn|gradle|make|platformio|pio) test)\b")
QUIET_TOOLS = {"ToolSearch", "TodoRead", "TaskGet", "TaskList", "ExitPlanMode", "EnterPlanMode"}


def activity(tool, tool_input=None):
    """What a tool call means to a listener: read, edit, test, git, shell, web, agent, plan or other.

    None for bookkeeping tools nobody wants narrated.
    """
    if tool in QUIET_TOOLS:
        return None
    if tool in ("Read", "Grep", "Glob", "LS", "NotebookRead"):
        return "read"
    if tool in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        return "edit"
    if tool in ("Bash", "PowerShell"):
        command = str((tool_input or {}).get("command", ""))
        if TESTS.search(command):
            return "test"
        if re.match(r"\s*(cd\s+\S+\s*(&&|;)\s*)?git\b", command):
            return "git"
        return "shell"
    if tool in ("WebSearch", "WebFetch"):
        return "web"
    if tool in ("Task", "Agent"):
        return "agent"
    if tool in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return "plan"
    return "other"


def progress(kind, h, now=None):
    """A short line about what Claude is doing (`kind` from `activity`)."""
    return _fill(_draw(f"progress-{kind}", lines.PROGRESS[kind], now or datetime.now()), h)


def stock_lines(h, expressive=False):
    """Every short line she may need in a hurry (acknowledgements, answers to
    her name, thinking sounds, progress), to synthesize ahead of time."""
    banks = [lines.ACKS, lines.WAKE, lines.WAKE_TIMEOUT, lines.WAKE_CANCEL, lines.THINKING]
    banks += list(lines.PROGRESS.values()) + ([lines.THINKING_V3] if expressive else [])
    return list(dict.fromkeys(_fill(text, h) for bank in banks for text, _, _ in bank))


def wake(h, flavor=False, now=None):
    """Her answer when called by name: short, or (`flavor`) a nod to the films."""
    return _fill(_draw("wake", lines.WAKE, now or datetime.now(), tone=2 if flavor else 1), h)


def wake_timeout(h, now=None):
    return _fill(_draw("wake-timeout", lines.WAKE_TIMEOUT, now or datetime.now()), h)


def wake_cancel(h, now=None):
    return _fill(_draw("wake-cancel", lines.WAKE_CANCEL, now or datetime.now()), h)
