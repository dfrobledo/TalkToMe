"""Rachel keeps you company while Claude works on something you said out loud.

A long silence after speaking feels like nobody heard. So while a turn
started by dictation is running, a worker watches the session transcript
and now and then says something short: what Claude is doing ("Corriendo
las pruebas...") or the small sounds of someone thinking ("Mmm, a ver...").

It never slows Claude down (it only reads the transcript), never talks over
anyone (it gives up if the voice is busy), and spaces its lines further
apart the longer the turn goes. Every line is short and cached: after the
first time they cost no ElevenLabs characters. The reply worker ends it:
claiming the session kills this one.
"""
import time

from . import persona, player, transcript
from .config import STATE_DIR

# Seconds of quiet before the first line (the acknowledgement just played),
# growth of the gap after each one, and its ceiling.
FIRST_GAP = 5.0
GROWTH = 1.35
MAX_GAP = 30.0
MAX_TURN = 15 * 60
POLL = 0.5


def turn_done(session):
    """The Stop hook's mark: the reply is on its way, stop talking."""
    return player.session_dir(session) / "turn-done"


def gap(said):
    """Quiet needed before line number `said` + 1."""
    return min(FIRST_GAP * GROWTH ** said, MAX_GAP)


def tone(said):
    """Thinking sounds grow into words the longer Claude takes."""
    return 1 if said < 2 else 2 if said < 5 else 3


class Companion:
    def __init__(self, cfg, session, transcript_path, clock=time.monotonic, sleep=time.sleep, say=None):
        self.cfg, self.session, self.path = cfg, session, transcript_path
        self.clock, self.sleep = clock, sleep
        self.say = say or (lambda text: player.speak(text, cfg, session=session, wait=0))
        self.said, self.last_kind = 0, None

    def next_line(self, kinds):
        """What to say now, given the kinds of work seen since the last line."""
        h = self.cfg["honorific"]
        fresh = [kind for kind in kinds if kind and kind != self.last_kind]
        if fresh:
            self.last_kind = fresh[-1]
            return persona.progress(fresh[-1], h)
        return persona.thinking(h, tone(self.said), expressive=self.cfg["model_id"] == "eleven_v3")

    def run(self):
        started = self.clock()
        quiet_since = started
        offset = transcript.size(self.path)
        kinds = []
        done = turn_done(self.session)
        while self.clock() - started < MAX_TURN:
            self.sleep(POLL)
            if done.exists() or (STATE_DIR / "muted").exists():
                return
            calls, offset = transcript.tool_calls(self.path, offset)
            kinds += [persona.activity(name, args) for name, args in calls]
            if self.clock() - quiet_since < gap(self.said) or player.busy():
                continue
            if self.say(self.next_line(kinds)):
                self.said += 1
            kinds = []
            quiet_since = self.clock()


def accompany(cfg, session, transcript_path):
    """Detached worker `_acompana`: company for one voice turn of `session`."""
    # A very quick turn may already be over: claiming now would cut its reply.
    if turn_done(session).exists():
        return
    player.claim(session)
    try:
        Companion(cfg, session, transcript_path).run()
    finally:
        player.release(session)
