"""Audio playback, background workers and interruption."""
import os
import re
import shutil
import signal
import subprocess
import sys
import time

from . import tts
from .config import ROOT, STATE_DIR

# Whoever is speaking right now: one voice, one sound card, for every session.
PID_FILE = STATE_DIR / "speaking.pid"
# The worker has no console; on Windows each console program it starts
# (ffplay, mpv, claude) would otherwise pop up a window of its own.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
LOG_FILE = STATE_DIR / "talktome.log"

# Streaming players start talking while ElevenLabs is still generating.
STREAM_PLAYERS = {
    "mpv": ["mpv", "--no-video", "--really-quiet", "--no-terminal", "-"],
    "ffplay": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-"],
}
# Fallbacks: wait for the whole utterance, then play a WAV file.
FILE_PLAYERS = {
    "afplay": ["afplay"],
    "paplay": ["paplay"],
    "pw-play": ["pw-play"],
    "aplay": ["aplay", "-q"],
}


def _stream_cmd(cfg):
    choice = cfg.get("player", "auto")
    names = list(STREAM_PLAYERS) if choice == "auto" else [choice]
    for name in names:
        if name in STREAM_PLAYERS and shutil.which(name):
            return STREAM_PLAYERS[name]
    return None


def _file_cmd():
    for name, cmd in FILE_PLAYERS.items():
        if shutil.which(name):
            return cmd
    return None


def describe(cfg):
    cmd = _stream_cmd(cfg)
    if cmd:
        return f"{cmd[0]} (streaming, baja latencia)"
    if sys.platform == "win32":
        return "winsound (sin streaming; instala mpv para menor latencia)"
    cmd = _file_cmd()
    return f"{cmd[0]} (sin streaming)" if cmd else None


def _play_wav(data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / "last.wav"
    path.write_bytes(data)
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME)
        return
    cmd = _file_cmd()
    if not cmd:
        raise tts.TTSError("No hay reproductor de audio: instala mpv o ffmpeg.")
    subprocess.run(cmd + [str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def play_mp3(data, cfg):
    """Play an mp3 already in memory. Returns False if no player can do it."""
    cmd = _stream_cmd(cfg)
    if not cmd:
        return False
    subprocess.run(cmd, input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    return True


def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


# Each Claude Code session (one per terminal) keeps its own last reply, so
# "repite" and "detalle" never pick up what another project said.
SESSIONS = STATE_DIR / "sessions"
# The session whose reply was said last: what `talktome repite` repeats
# from a plain console.
LAST_SESSION = STATE_DIR / "last-session"
# The project Rachel spoke from last, to notice when her voice changes project.
LAST_VOICE = STATE_DIR / "last-voice"
SESSION_DAYS = 14


def session_dir(session=None):
    """Folder of one Claude Code session; without one, the last that spoke."""
    session = session or _read(LAST_SESSION).strip()
    safe = re.sub(r"[^\w-]", "", session)[:80]
    return SESSIONS / safe if safe else STATE_DIR


def _reply(session, suffix):
    return (session_dir(session) / "last-reply").with_suffix(suffix)


def remember_project(session, project):
    """Note which project `session` works on, so its voice can be told apart."""
    if not session:
        return
    folder = session_dir(session)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project").write_text(project, encoding="utf-8")


def keep_markdown(session, text):
    """The last reply as shown on screen, for "detalle"."""
    folder = session_dir(session)
    folder.mkdir(parents=True, exist_ok=True)
    _reply(session, ".md").write_text(text, encoding="utf-8")


def last_markdown(session=None):
    return _read(_reply(session, ".md"))


def _keep_reply(session, text, data, ext):
    for old in ("mp3", "wav"):
        _reply(session, f".{old}").unlink(missing_ok=True)
    _reply(session, f".{ext}").write_bytes(data)
    _reply(session, ".audio.txt").write_text(text, encoding="utf-8")


def last_spoken(session=None):
    """Text of the last reply Rachel said out loud for `session`."""
    return _read(_reply(session, ".txt"))


def replay(cfg, session=None):
    """Say the last reply of `session` again. Returns False if there is none.

    Its saved audio is replayed for free; only if it was cut off halfway
    (the user interrupted it) is it synthesized again.
    """
    text = last_spoken(session)
    if not text:
        return False
    with _Floor(session, 300) as ok:
        if not ok:
            return True
        if _read(_reply(session, ".audio.txt")) == text:
            mp3, wav = _reply(session, ".mp3"), _reply(session, ".wav")
            if mp3.exists() and play_mp3(mp3.read_bytes(), cfg):
                return True
            if wav.exists():
                _play_wav(wav.read_bytes())
                return True
        _say(text, cfg, keep=True, session=session)
    return True


def speak(text, cfg, keep=False, session=None, intro=None, wait=300):
    """Say `text` once it is Rachel's turn, and block until done.

    Another session speaking is never cut off: this waits up to `wait`
    seconds for it to finish (0: give up at once) and returns False if the
    floor never came free. `intro(previous_project)` may return a line to
    say first, such as the project Rachel now speaks from.

    With keep=True the audio is also saved as the session's last reply.
    """
    text = text.strip()
    if not text:
        return True
    floor = _Floor(session, wait)
    with floor as ok:
        if not ok:
            return False
        first = intro(floor.previous) if intro else ""
        if first:
            _say(first, cfg)
        _say(text, cfg, keep=keep, session=session)
    return True


def _say(text, cfg, keep=False, session=None):
    """Synthesize and play `text`. Short phrases are cached on disk."""
    cmd = _stream_cmd(cfg)
    if keep:
        session_dir(session).mkdir(parents=True, exist_ok=True)
        _reply(session, ".txt").write_text(text, encoding="utf-8")
        if session:
            LAST_SESSION.write_text(session, encoding="utf-8")
    cacheable = len(text) <= cfg.get("cache_max_chars", 0)
    cached = tts.cache_path(text, cfg, "mp3" if cmd else "wav")

    if not cmd:
        data = cached.read_bytes() if cached.exists() else tts.wav(text, cfg)
        if cacheable and not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        if keep:
            _keep_reply(session, text, data, "wav")
        _play_wav(data)
        return

    chunks = [cached.read_bytes()] if cached.exists() else tts.stream(text, cfg)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=NO_WINDOW)
    audio, complete = [], False
    try:
        for chunk in chunks:
            proc.stdin.write(chunk)
            proc.stdin.flush()
            audio.append(chunk)
        complete = True
    except (BrokenPipeError, OSError):
        pass  # Player was killed: we got interrupted.
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.wait()
    if complete and keep:
        _keep_reply(session, text, b"".join(audio), "mp3")
    if complete and cacheable and not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(b"".join(audio))


class _Floor:
    """Hold the floor while speaking. `previous`: the project heard before this one."""

    def __init__(self, session, wait):
        self.session, self.wait, self.took, self.previous = session, wait, False, ""

    def __enter__(self):
        if _pid(PID_FILE) != os.getpid():
            deadline = time.monotonic() + self.wait
            while not _grab():
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.3)
            self.took = True
            if (STATE_DIR / "muted").exists():  # muted while waiting
                return False
        self.previous = _read(LAST_VOICE)
        if self.session:  # a console command belongs to no project
            LAST_VOICE.write_text(_read(session_dir(self.session) / "project"), encoding="utf-8")
        return True

    def __exit__(self, *exc):
        if self.took:
            _drop(PID_FILE)


def _pid(path):
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return None


def _drop(path):
    """Delete a pid file, but only if it is ours."""
    if _pid(path) == os.getpid():
        try:
            path.unlink()
        except OSError:
            pass


def _grab():
    """Take the floor if it is free. Atomic: two sessions never talk at once."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(PID_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid = _pid(PID_FILE)
            if pid == os.getpid():
                return True
            try:
                fresh = time.time() - PID_FILE.stat().st_mtime < 5
            except OSError:
                continue  # just released
            # A pid that is still alive holds it; an empty file is being written.
            if (pid and _alive(pid)) or (pid is None and fresh):
                return False
            try:
                PID_FILE.unlink()  # its owner died without releasing it
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    return False


def _kill(pid):
    if not pid or pid == os.getpid():
        return False
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], creationflags=NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.killpg(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    return True


def stop(session=None):
    """Silence Rachel. With a session, only what that session says or is about to say."""
    path = session_dir(session) / "worker.pid" if session else PID_FILE
    pid = _pid(path)
    if not _kill(pid):
        return False
    try:
        path.unlink()
    except OSError:
        pass
    return True


def _alive(pid):
    if sys.platform == "win32":
        # os.kill(pid, 0) would send CTRL_C_EVENT on Windows; ask the kernel.
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def busy():
    """Is another process speaking right now?"""
    pid = _pid(PID_FILE)
    return pid is not None and pid != os.getpid() and _alive(pid)


def wait_turn(timeout):
    """Wait until nobody is speaking. False if it took longer than `timeout`."""
    deadline = time.monotonic() + timeout
    while busy():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.5)
    return True


def claim(session=None):
    """Mark this process as the voice of `session`, cutting off what it was saying.

    Other sessions are left alone: `speak` waits for their turn to end.
    Without a session (a command typed in a console) it takes the floor
    at once, interrupting whoever is speaking.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not session:
        stop()
        PID_FILE.write_text(str(os.getpid()))
        return
    stop(session)
    folder = session_dir(session)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "worker.pid").write_text(str(os.getpid()))
    _prune()


def release(session=None):
    _drop(PID_FILE)
    if session:
        _drop(session_dir(session) / "worker.pid")


def _prune():
    """Forget sessions untouched for SESSION_DAYS days."""
    limit = time.time() - SESSION_DAYS * 86400
    try:
        old = [d for d in SESSIONS.iterdir() if d.is_dir() and d.stat().st_mtime < limit]
    except OSError:
        return
    for folder in old:
        shutil.rmtree(folder, ignore_errors=True)


def spawn(*args):
    """Run `talktome.py <args>` detached so Claude Code never waits on audio."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ROOT / "talktome.py"), *args]
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        try:
            subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
        except OSError:
            subprocess.Popen(cmd, creationflags=flags, **kwargs)
    else:
        subprocess.Popen(cmd, start_new_session=True, **kwargs)
