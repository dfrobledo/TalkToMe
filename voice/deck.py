"""Rachel's memory between hook calls: shuffled decks, waits and invented lines.

Every hook runs in a fresh process, so what Rachel already said lives in
~/.talktome/lines.json.
"""
import json
import os
import random
import time

from .config import STATE_DIR

STATE_FILE = STATE_DIR / "lines.json"


def load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def draw(name, options, fits=lambda line: True, rng=random):
    """Next line of deck `name`: no line comes back until every fitting one was said.

    The deck is a shuffled queue. Lines that do not fit right now (wrong
    time of day, wrong tone) keep their place; once no fitting line is
    left, the ones already said are shuffled back in behind them, never
    starting with the one just said.
    """
    options = list(dict.fromkeys(options))
    state = load()
    queue = [line for line in state.get("decks", {}).get(name, []) if line in options]
    last = state.get("last", {}).get(name)
    pick = next((line for line in queue if fits(line)), None)
    if pick is None:
        said = [line for line in options if line not in queue]
        rng.shuffle(said)
        queue += said
        fitting = [line for line in queue if fits(line)]
        if not fitting:
            return ""
        pick = next((line for line in fitting if line != last), fitting[0])
    queue.remove(pick)
    state.setdefault("decks", {})[name] = queue
    state.setdefault("last", {})[name] = pick
    save(state)
    return pick


def waits(now=None, window=90 * 60, top=3):
    """How many times in a row the user has kept Rachel waiting: 1, 2 ... `top`.

    Counts idle reminders within `window` seconds of each other; after the
    `top` one the count starts over, so the drama stays rare.
    """
    now = time.time() if now is None else now
    state = load()
    recent = [t for t in state.get("waits", []) if now - t < window]
    recent.append(now)
    count = len(recent)
    state["waits"] = [] if count >= top else recent
    save(state)
    return min(count, top)


def first_time_today(key, today):
    """True only the first time it is asked for `key` on `today`."""
    state = load()
    if state.get("said_on", {}).get(key) == today:
        return False
    state.setdefault("said_on", {})[key] = today
    save(state)
    return True


def invented():
    return load().get("invented", [])


def add_invented(lines, keep):
    """Store new lines, keeping only the `keep` most recent. Returns those added."""
    state = load()
    known = state.get("invented", [])
    added = [line for line in lines if line not in known]
    state["invented"] = (known + added)[-keep:] if keep > 0 else []
    save(state)
    return added
