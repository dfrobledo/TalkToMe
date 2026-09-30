"""Rachel listens: hold a key, speak, and it goes to Claude Code as a typed prompt.

    hold the key ─► the microphone records at once; Rachel stops talking
                 ─► audio streams to Scribe Realtime while you speak
    release it   ─► the text is ready a moment later (batch Scribe if not)
                 ─► typed into the window that had the focus, plus Enter
                 ─► "Entendido, señor.": Rachel heard you

The prompt reaches Claude Code exactly as if typed, so its hooks apply:
"repite" and "detalle" are handled by Rachel without spending a turn, and
a dictated prompt gets company while Claude works (companion.py).
Only "calla" is handled here: pressing the key already silenced her.
"""
import os
import threading
import time

from . import alerts, hooks, mic, persona, player, realtime, stt, wake
from .config import STATE_DIR
from .tts import TTSError

PID_FILE = STATE_DIR / "listen.pid"
# The last dictation, kept to re-check what Scribe heard: talktome oye <file>.
LAST_AUDIO = STATE_DIR / "dictado.wav"
POLL = 0.02


def _hush():
    # taskkill takes a moment on Windows: never let it delay the microphone.
    threading.Thread(target=player.stop, daemon=True).start()


def _acknowledge(cfg):
    """Rachel says she heard, from a worker of her own (a new dictation can cut it off)."""
    if cfg.get("voice_ack", True) and cfg.get("enabled", True) and not cfg.get("muted") and cfg.get("api_key"):
        hooks._enqueue("say", {"text": persona.ack(cfg["honorific"]), "callsign": False})


def _stream(cfg):
    return realtime.Stream(cfg) if cfg.get("stt_realtime", True) else None


class Listener:
    """One hold-to-talk dictation after another. `desk` is the desktop (mic.Desk)."""

    def __init__(self, cfg, desk, transcribe=stt.transcribe, stream=_stream, hush=_hush, acknowledge=_acknowledge,
                 report=alerts.report, recorder=None, clock=time.monotonic, sleep=time.sleep, out=print):
        self.cfg, self.desk, self.transcribe, self.stream = cfg, desk, transcribe, stream
        self.recorder = recorder or desk.recorder
        self.hush, self.acknowledge, self.report = hush, acknowledge, report
        self.clock, self.sleep, self.out = clock, sleep, out

    def run(self, alive=None, every=5.0):
        """Dictations until Ctrl+C, or until `alive()` says Claude Code is gone."""
        while True:
            waited = 0.0
            while not self.desk.key_down():
                self.sleep(POLL)
                waited += POLL
                if alive and waited >= every:
                    if not alive():
                        return
                    waited = 0.0
            self.dictate()
            while self.desk.key_down():  # held past the time limit
                self.sleep(POLL)

    def dictate(self):
        """Record while the key is held, then deliver what was said. Returns the text typed."""
        window = self.desk.foreground()
        recorder = self.recorder()
        stream = self.stream(self.cfg)
        try:
            recorder.start(on_chunk=stream.feed if stream else None)
        except mic.MicError as e:
            if stream:
                stream.cancel()
            return self._fail(str(e), "mic")
        self.desk.beep("start")
        self.hush()
        started = self.clock()
        limit = self.cfg.get("listen_max_seconds", 120)
        while self.desk.key_down() and self.clock() - started < limit:
            self.sleep(POLL)
        seconds = self.clock() - started
        if seconds < self.cfg.get("listen_min_seconds", 0.4):
            recorder.cancel()  # a tap, not a dictation: a short beep says so
            if stream:
                stream.cancel()
            self.desk.beep("short")
            return ""
        try:
            audio = recorder.stop(LAST_AUDIO)
        except (mic.MicError, OSError) as e:
            if stream:
                stream.cancel()
            return self._fail(str(e), "mic")
        released = self.clock()
        text, how, realtime_error = None, "por lotes", None
        if stream:
            try:
                text, how = stream.finish(self.cfg.get("stt_realtime_timeout", 5)), "en tiempo real"
            except TTSError as e:
                realtime_error = e
                hooks.log(f"dictado: {e}; paso a Scribe por lotes")
        if text is None:
            try:
                text = self.transcribe(audio, self.cfg)
            except (TTSError, OSError) as e:
                kind = alerts.classify(e)
                return self._fail(str(e), kind if kind != "crash" else "stt")
        if realtime_error:
            self.report("realtime", self.cfg, str(realtime_error))  # works, only slower
        text = stt.clean(text)
        took = self.clock() - released
        if not text:
            return self._fail(f"dictado de {seconds:.1f} s sin palabras")
        if hooks.is_stop(text):
            hooks.log(f"dictado: «{text}» → Rachel calla")
            self.out(f"» {text}  (Rachel calla)")
            return ""
        hooks.mark_dictated(text)
        blocked = None
        try:
            typed = self.desk.type_text(text, window)
        except mic.MicError as e:
            typed, blocked = False, e
            hooks.log(f"dictado: {e}")
        if not typed:
            self.desk.copy(text)
            self.desk.beep("error")
            hooks.log(f"dictado: la ventana cambió, texto en el portapapeles ({len(text)} car.)")
            self.report(alerts.classify(blocked) if blocked else "clipboard", self.cfg, str(blocked or ""))
            self.out(f"» {text}  (quedó en el portapapeles)")
            return ""
        self.acknowledge(self.cfg)
        hooks.log(f"dictado: {seconds:.1f} s de voz → {len(text)} car., texto {took:.1f} s después de soltar ({how})")
        self.out(f"» {text}")
        return text

    def _fail(self, why, kind=None):
        hooks.log(f"dictado: {why}")
        self.out(f"  ({why})")
        self.desk.beep("error")
        if kind:
            self.report(kind, self.cfg, why)
        return ""


def choose_window(desk):
    """Where a spoken command goes: the Claude Code terminal in front, or else
    the one used last. None if no open session has a window left."""
    windows = [window for window, _ in hooks.session_windows()]
    front = desk.foreground()
    if front in windows:
        return front
    return next((window for window in windows if desk.alive(window)), None)


def deliverer(cfg, desk, out=print, acknowledge=_acknowledge, report=alerts.report):
    """`deliver(text)` for commands said to her by name: to the right terminal."""
    def deliver(text, error=None):
        if error is not None:
            kind = alerts.classify(error)
            report(kind if kind != "crash" else "stt", cfg, str(error))
            return
        window = choose_window(desk)
        if not window:
            desk.copy(text)
            report("no_target", cfg)
            out(f"» {text}  (sin terminal: quedó en el portapapeles)")
            return
        hooks.mark_dictated(text)
        blocked = None
        try:
            typed = desk.type_text(text, window)
        except mic.MicError as e:
            typed, blocked = False, e
        if not typed:
            desk.copy(text)
            report(alerts.classify(blocked) if blocked else "focus", cfg, str(blocked or ""))
            out(f"» {text}  (quedó en el portapapeles)")
            return
        acknowledge(cfg)
        hooks.log(f"activación → {len(text)} car. a la terminal")
        out(f"» {text}")

    return deliver


def _say_blocking(cfg):
    def say(text):
        if cfg.get("muted") or not cfg.get("enabled", True):
            return
        try:
            player.speak(text, cfg, wait=0)
        except Exception as e:  # her answer failing must not stop the listening
            hooks.log(f"activación: no pude responder: {e}")
            alerts.report(alerts.classify(e), cfg, str(e))
    return say


def _echo(words):
    def echo():
        said = wake.normalize(player.speaking())
        return bool(said) and any(wake.normalize(w) in said for w in words)
    return echo


def start_wake(cfg, desk, out=print):
    """Listen for her name in the background. Returns (hub, stop event) or (None, None)."""
    if not wake.enabled(cfg):
        ready, why = wake.engine(cfg)
        if cfg.get("wake") is True:
            hooks.log(f"activación por voz: {why}")
            alerts.report("wake", cfg, why)
        return None, None
    try:
        spotter = wake.VoskSpotter(wake.model_path(cfg))
        hub = wake.Hub(mic.Recorder())
        hub.start()
    except Exception as e:
        hooks.log(f"activación por voz: {e}")
        alerts.report(alerts.classify(e) if isinstance(e, mic.MicError) else "wake", cfg, str(e))
        return None, None
    words = list(dict.fromkeys(wake.WAKE_WORDS + list(cfg.get("wake_words") or [])))
    listener = wake.Wake(cfg, spotter, say=_say_blocking(cfg), deliver=deliverer(cfg, desk, out),
                         transcribe=stt.transcribe, stop_voice=_hush, stream=_stream, echo=_echo(words),
                         paused=lambda: hub.tap is not None, drain=hub.drain, log=hooks.log)
    stop = threading.Event()
    wake.start_thread(hub.run, listener, stop)
    hooks.log("activación por voz: escuchando su nombre")
    out("Y diga «Rachel» cuando la necesite.")
    return hub, stop


def running():
    """pid of the listener already running, if any: two would type everything twice."""
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        return None
    return pid if pid != os.getpid() and player._alive(pid) else None


def _lock():
    """Become the one listener. Atomic: two sessions opening at once start only one."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        try:
            fd = os.open(PID_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            other = running()
            if other:
                raise mic.MicError(f"Ya hay una escucha activa (proceso {other}).")
            try:
                if time.time() - PID_FILE.stat().st_mtime < 2 and not PID_FILE.read_text():
                    raise mic.MicError("Otra escucha está arrancando.")  # being written right now
                PID_FILE.unlink()  # its owner died
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return
    raise mic.MicError("No pude tomar la escucha.")


def stop_listening():
    """End the listener running in the background. False if there was none."""
    pid = running()
    if pid:
        player._kill(pid)
        PID_FILE.unlink(missing_ok=True)
    return bool(pid)


def serve(cfg, key=None, out=print, background=False):
    """`talktome escucha`: listen until Ctrl+C. In the `background` (launched by
    SessionStart) there is no console, and it leaves once Claude Code closes."""
    key = key or cfg.get("listen_key", "F9")
    _lock()
    try:
        desk = mic.Desk(key)
    except Exception:
        PID_FILE.unlink(missing_ok=True)
        raise
    alive = None
    idle = cfg.get("listen_idle_minutes", 120)
    hooks.LISTEN_DOZED.unlink(missing_ok=True)
    if background:
        alive = lambda: hooks.claude_open(idle)  # noqa: E731
        hooks.log(f"escucha en segundo plano: mantenga {key} para hablar")
    try:
        out(f"Rachel escucha: mantenga {key} mientras habla y suéltela para enviar. Ctrl+C para salir.")
        if not desk.exclusive:
            out(f"  Aviso: otro programa ya usa {key}; la tecla también le llegará a la ventana activa.")
        hub, stop_wake = start_wake(cfg, desk, out)
        recorder = hub.recorder_for_key if hub else None
        try:
            Listener(cfg, desk, out=out, recorder=recorder).run(alive=alive)
        finally:
            if hub:
                stop_wake.set()
                hub.close()
        if background:
            if any(hooks.OPEN_SESSIONS.glob("*")):
                hooks.LISTEN_DOZED.touch()  # the next prompt wakes it up
                hooks.log(f"escucha en pausa: {idle} min sin actividad en Claude Code")
            else:
                hooks.log("escucha terminada: Claude Code se cerró")
    except KeyboardInterrupt:
        out("Rachel deja de escuchar.")
    finally:
        desk.close()
        try:
            if int(PID_FILE.read_text()) == os.getpid():
                PID_FILE.unlink()
        except (OSError, ValueError):
            pass
