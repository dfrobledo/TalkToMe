"""Rachel, always listening for her name.

    "Rachel, corre las pruebas."   in one breath: straight to Claude Code
    "Rachel..."  "¿Sí, señor?"  "Corre las pruebas."   with a pause

Her name is spotted on this machine (Vosk, offline, a small Spanish model):
nothing leaves the PC until she is called. Only then does the command go to
Scribe, the same as a dictation with the key.

Pieces, all testable without a microphone:
- `find_wake` / `strip_wake`: the name at the start of what was said.
- `Gate`: an energy gate, so the recognizer rests while the room is quiet.
- `Wake`: the conversation (asleep → called → listening → deliver).
- `VoskSpotter`: the local recognizer (optional dependency: `pip install vosk`).
- `Hub` / `Tap`: one microphone shared by the name spotter and the F9 key.
"""
import collections
import json
import math
import re
import sys
import threading
import unicodedata
from array import array
from pathlib import Path

from .config import STATE_DIR

MODEL_NAME = "vosk-model-small-es-0.42"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
# Spanish ears hear "Rachel" many ways; `wake_words` in the config adds more.
WAKE_WORDS = ["rachel", "rachael", "raquel", "reichel", "rechel", "raichel", "ray chel", "rei chel"]
# May come before her name: "oye, Rachel".
LEAD = {"oye", "hey", "ey", "ei", "ok", "okay", "hola", "eh", "este", "disculpa", "perdon", "a", "ver"}
CANCEL = {"nada", "olvidalo", "no nada", "nada nada", "olvidalo nada", "no importa", "cancela", "cancelar",
          "dejalo", "ya no", "nada olvidalo", "no olvidalo"}
FILLER = {"eh", "este", "mmm", "em", "ah"}


def normalize(text):
    """Lowercase words without accents or punctuation."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def find_wake(words, wake_words=WAKE_WORDS, max_lead=2):
    """(start, end) word indexes of her name at the start of `words`, or None.

    Only a couple of lead words ("oye", "hey") may come before it: "le dije
    a Rachel que..." in a conversation is not a call.
    """
    variants = [normalize(w).split() for w in wake_words]
    for start in range(min(max_lead, len(words)) + 1):
        if any(w not in LEAD for w in words[:start]):
            break
        for variant in variants:
            if variant and words[start:start + len(variant)] == variant:
                return start, start + len(variant)
    return None


def strip_wake(text, wake_words=WAKE_WORDS):
    """What was said after her name ("Rachel, corre las pruebas" → "Corre las pruebas")."""
    tokens = list(re.finditer(r"\w+", text))
    found = find_wake([normalize(t.group()) for t in tokens], wake_words)
    if not found:
        return text.strip()
    rest = text[tokens[found[1] - 1].end():].lstrip(" ,.;:!?-—…")
    # Capitalize the first letter, after any opening "¿" or "¡".
    return re.sub(r"^([¿¡]*)(\w)", lambda m: m.group(1) + m.group(2).upper(), rest)


def is_cancel(text):
    return normalize(text) in CANCEL


def level(pcm):
    """RMS of 16-bit mono PCM."""
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class Gate:
    """Lets audio through while someone speaks (plus a little before and after).

    The noise floor adapts: quickly down, slowly up, so a fan or the rain on
    the window does not count as speech.
    """

    def __init__(self, hangover=2.0, chunk=0.1, preroll=3, min_level=300.0, ratio=3.0):
        self.hangover, self.chunk, self.min_level, self.ratio = hangover, chunk, min_level, ratio
        self.pre = collections.deque(maxlen=preroll)
        self.floor, self.open, self.quiet = None, False, 0.0

    def speech(self, value):
        return value > max(self.min_level, (self.floor or 0) * self.ratio)

    def _adapt(self, value):
        if self.floor is None:
            self.floor = min(value, self.min_level)  # starting mid-word must not raise the bar
        elif value < self.floor:
            self.floor = 0.7 * self.floor + 0.3 * value
        else:
            self.floor = 0.995 * self.floor + 0.005 * value

    def push(self, pcm):
        """(chunks to hand the recognizer, whether the gate just closed)."""
        value = level(pcm)
        loud = self.speech(value)
        self._adapt(value)
        if self.open:
            self.quiet = 0.0 if loud else self.quiet + self.chunk
            if self.quiet >= self.hangover:
                self.open = False
                self.pre.clear()
                return [pcm], True
            return [pcm], False
        if loud:
            self.open, self.quiet = True, 0.0
            chunks = list(self.pre) + [pcm]
            self.pre.clear()
            return chunks, False
        self.pre.append(pcm)
        return [], False


class Wake:
    """The conversation around her name. Feed it microphone chunks with `handle`.

    `say(text)` speaks and returns when done; `deliver(text)` routes a command
    (Claude Code, "calla", "nada"...); `stop_voice()` silences her; `echo()`
    says whether her own voice is saying her name right now; `paused()` is
    true while the F9 key has the microphone; `drain()` drops audio queued
    while she was talking.
    """

    def __init__(self, cfg, spotter, say, deliver, transcribe, stop_voice=lambda: None, stream=lambda cfg: None,
                 echo=lambda: False, paused=lambda: False, drain=lambda: None, clock=None, log=lambda m: None,
                 persona_=None, rng=None, is_stop=None):
        import random
        import time

        from . import persona

        self.cfg, self.spotter, self.say, self.deliver, self.transcribe = cfg, spotter, say, deliver, transcribe
        self.stop_voice, self.stream, self.echo, self.paused, self.drain = stop_voice, stream, echo, paused, drain
        self.clock, self.log = clock or time.monotonic, log
        self.persona, self.rng = persona_ or persona, rng or random.Random()
        if is_stop is None:
            from .hooks import is_stop
        self.is_stop = is_stop
        self.words = list(dict.fromkeys(WAKE_WORDS + list(cfg.get("wake_words") or [])))
        self.gate = Gate()
        self._sleep()

    def _sleep(self):
        self.state, self.utterance, self.heard_at = "asleep", [], None
        self.command, self.spoke, self.live = [], False, None

    def handle(self, pcm):
        if self.paused():
            if self.state != "asleep":
                self._abandon()
            return
        if self.state == "listening":
            return self._listen(pcm)
        chunks, closed = self.gate.push(pcm)
        for chunk in chunks:
            self.utterance.append(chunk)
            if self.live:
                self.live.feed(chunk)
            kind, text = self.spotter.feed(chunk)
            if kind == "final":
                self._heard(text)
            elif self.state == "asleep":
                self._partial(text)
            if self.state == "listening":
                return  # she answered: what follows is the order, not more of this
        del self.utterance[:-300]  # at most 30 s
        if closed:
            self._heard(self.spotter.flush())
            self.utterance = []
        elif self.state == "called" and self.clock() - self.heard_at > 6:
            self._heard(self.spotter.flush())  # a noisy room never ends the utterance

    def _partial(self, text):
        if text and find_wake(normalize(text).split(), self.words) and not self.echo():
            self.state, self.heard_at = "called", self.clock()
            self.stop_voice()  # she hears her name: she stops at once
            # The order may come in the same breath: Scribe starts listening now.
            self.live = self.stream(self.cfg)
            if self.live:
                for chunk in self.utterance:
                    self.live.feed(chunk)

    def _heard(self, text):
        """An utterance ended: was it for her, and did it carry the order?"""
        words = normalize(text).split()
        found = find_wake(words, self.words) if words else None
        audio, self.utterance = b"".join(self.utterance), []
        live, self.live = self.live, None
        if not found or (self.state == "asleep" and self.echo()):
            if live:
                live.cancel()
            self._sleep()
            return
        after = [w for w in words[found[1]:] if w not in FILLER]
        if after:
            self.log(f"activación: «{text}» de un tirón")
            self._sleep()
            rest = " ".join(after)
            if self.is_stop(rest) or is_cancel(rest):
                if live:
                    live.cancel()
                if is_cancel(rest):
                    self.say(self.persona.wake_cancel(self.cfg["honorific"]))
                    self.drain()
                # "Rachel, calla": she already stopped on hearing her name.
            else:
                self._process(audio, live)
            self.spotter.reset()
            return
        if live:
            live.cancel()
        self.log("activación: su nombre, espera la orden")
        flavor = self.rng.random() < self.cfg.get("wake_flavor", 0.3)
        self.say(self.persona.wake(self.cfg["honorific"], flavor=flavor))
        self.drain()  # what the mic heard while she spoke is her own voice
        self.spotter.reset()
        self.state, self.heard_at = "listening", self.clock()
        self.command, self.spoke, self.last_voice = [], False, None
        self.live = self.stream(self.cfg)

    def _listen(self, pcm):
        now = self.clock()
        self.command.append(pcm)
        if self.live:
            self.live.feed(pcm)
        if self.gate.speech(level(pcm)):
            self.spoke, self.last_voice = True, now
        if not self.spoke:
            if now - self.heard_at > self.cfg.get("wake_timeout", 6):
                if self.live:
                    self.live.cancel()
                self.log("activación: no dijo nada")
                self._sleep()
                self.say(self.persona.wake_timeout(self.cfg["honorific"]))
                self.drain()
            return
        done = now - self.last_voice >= self.cfg.get("wake_silence", 1.2)
        if done or now - self.heard_at > self.cfg.get("listen_max_seconds", 120):
            audio, live = b"".join(self.command), self.live
            self._sleep()
            self._process(audio, live)

    def _abandon(self):
        if self.live:
            self.live.cancel()
        self.spotter.reset()
        self._sleep()

    def _process(self, pcm, live):
        from . import stt
        from .tts import TTSError

        text = None
        if live:
            try:
                text = live.finish(self.cfg.get("stt_realtime_timeout", 5))
            except TTSError as e:
                self.log(f"activación: {e}; paso a Scribe por lotes")
        if text is None:
            try:
                text = self.transcribe(stt.wav_bytes(pcm), self.cfg)
            except (TTSError, OSError) as e:
                self.log(f"activación: {e}")
                self.deliver(None, error=e)
                return
        text = strip_wake(stt.clean(text), self.words)
        if not text:
            self.say(self.persona.wake_timeout(self.cfg["honorific"]))
        elif self.is_stop(text):
            pass
        elif is_cancel(text):
            self.say(self.persona.wake_cancel(self.cfg["honorific"]))
        else:
            self.deliver(text)
        self.spotter.reset()
        self.drain()


class VoskSpotter:
    """Vosk, offline speech recognition, listening for her name."""

    def __init__(self, model_path, rate=16000):
        import vosk

        vosk.SetLogLevel(-1)
        self.model = vosk.Model(str(model_path))
        self.rate = rate
        self.rec = vosk.KaldiRecognizer(self.model, rate)

    def feed(self, pcm):
        if self.rec.AcceptWaveform(pcm):
            return "final", json.loads(self.rec.Result()).get("text", "")
        return "partial", json.loads(self.rec.PartialResult()).get("partial", "")

    def flush(self):
        return json.loads(self.rec.FinalResult()).get("text", "")

    def reset(self):
        self.rec.Reset()


def model_path(cfg):
    return Path(cfg.get("wake_model") or STATE_DIR / "models" / MODEL_NAME)


def engine(cfg):
    """(ready, why not). Ready means Vosk is installed and its model is on disk."""
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False, "falta Vosk (talktome despierta --instalar)"
    if not (model_path(cfg) / "am").exists() and not (model_path(cfg) / "conf").exists():
        return False, f"falta el modelo en {model_path(cfg)} (talktome despierta --instalar)"
    return True, ""


def enabled(cfg):
    """Listen for her name? "auto" (default) turns it on once the engine is installed."""
    mode = cfg.get("wake", "auto")
    return mode is True or mode == "on" or (mode == "auto" and engine(cfg)[0])


def install(cfg, out=print):
    """Install Vosk (pip) and download the Spanish model (~40 MB)."""
    import io
    import subprocess
    import urllib.request
    import zipfile

    try:
        import vosk  # noqa: F401
    except ImportError:
        out("Instalando Vosk (pip install vosk)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "vosk"], check=True)
    target = model_path(cfg)
    if not target.exists():
        out(f"Descargando el modelo de español ({MODEL_NAME}, ~40 MB)...")
        with urllib.request.urlopen(MODEL_URL, timeout=120) as resp:
            data = resp.read()
        target.parent.mkdir(parents=True, exist_ok=True)
        zipfile.ZipFile(io.BytesIO(data)).extractall(target.parent)
    out(f"Listo: Vosk y el modelo en {target}.")


class Tap:
    """A recorder for the F9 key that borrows the always-open microphone.

    Same interface as mic.Recorder, but it starts instantly: no device to open.
    """

    def __init__(self, hub):
        self.hub, self.chunks, self.on_chunk = hub, [], None

    def start(self, on_chunk=None):
        self.chunks, self.on_chunk = [], on_chunk
        self.hub.tap = self

    def put(self, pcm):
        self.chunks.append(pcm)
        if self.on_chunk:
            self.on_chunk(pcm)

    def stop(self, path=None):
        from .stt import wav_bytes

        self.hub.tap = None
        data = wav_bytes(b"".join(self.chunks))
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return data

    def cancel(self):
        self.hub.tap = None


class Hub:
    """One microphone, always open: chunks go to the name spotter's queue, and
    to the F9 key's `Tap` while it records."""

    def __init__(self, recorder):
        import queue

        self.recorder, self.tap = recorder, None
        self.queue = queue.Queue()

    def start(self):
        self.recorder.start(on_chunk=self._chunk, keep=False)

    def _chunk(self, pcm):
        tap = self.tap
        if tap:
            tap.put(pcm)
        self.queue.put(pcm)

    def drain(self):
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Exception:
                return

    def run(self, wake, stop_event):
        """Feed `wake` until `stop_event` is set (its own thread)."""
        import queue

        while not stop_event.is_set():
            try:
                pcm = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            wake.handle(pcm)

    def recorder_for_key(self):
        return Tap(self)

    def close(self):
        self.recorder.cancel()


def start_thread(target, *args):
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread
