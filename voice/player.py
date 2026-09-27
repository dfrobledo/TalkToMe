"""Audio playback, background workers and interruption."""
import os
import shutil
import signal
import subprocess
import sys
import time

from . import tts
from .config import ROOT, STATE_DIR

PID_FILE = STATE_DIR / "speaking.pid"
# Audio of the last reply, so "repite" costs no ElevenLabs characters.
LAST_REPLY = STATE_DIR / "last-reply"
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


def _keep_reply(text, data, ext):
    for old in ("mp3", "wav"):
        LAST_REPLY.with_suffix(f".{old}").unlink(missing_ok=True)
    LAST_REPLY.with_suffix(f".{ext}").write_bytes(data)
    LAST_REPLY.with_suffix(".audio.txt").write_text(text, encoding="utf-8")


def replay(cfg):
    """Say the last reply again. Returns False if there is none.

    Its saved audio is replayed for free; only if it was cut off halfway
    (the user interrupted it) is it synthesized again.
    """
    text = _read(LAST_REPLY.with_suffix(".txt"))
    if not text:
        return False
    if _read(LAST_REPLY.with_suffix(".audio.txt")) == text:
        mp3, wav = LAST_REPLY.with_suffix(".mp3"), LAST_REPLY.with_suffix(".wav")
        if mp3.exists() and play_mp3(mp3.read_bytes(), cfg):
            return True
        if wav.exists():
            _play_wav(wav.read_bytes())
            return True
    speak(text, cfg, keep=True)
    return True


def speak(text, cfg, keep=False):
    """Say `text` and block until done. Short phrases are cached on disk.

    With keep=True the audio is also saved as the last reply for `replay`.
    """
    text = text.strip()
    if not text:
        return
    cmd = _stream_cmd(cfg)
    if keep:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_REPLY.with_suffix(".txt").write_text(text, encoding="utf-8")
    cacheable = len(text) <= cfg.get("cache_max_chars", 0)
    cached = tts.cache_path(text, cfg, "mp3" if cmd else "wav")

    if not cmd:
        data = cached.read_bytes() if cached.exists() else tts.wav(text, cfg)
        if cacheable and not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        if keep:
            _keep_reply(text, data, "wav")
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
        _keep_reply(text, b"".join(audio), "mp3")
    if complete and cacheable and not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(b"".join(audio))


def stop():
    """Silence whatever is being said right now."""
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        return False
    if pid == os.getpid():
        return False
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], creationflags=NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.killpg(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        PID_FILE.unlink()
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
    """Is another process speaking (or preparing to speak) right now?"""
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        return False
    return pid != os.getpid() and _alive(pid)


def wait_turn(timeout):
    """Wait until nobody is speaking. False if it took longer than `timeout`."""
    deadline = time.monotonic() + timeout
    while busy():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.5)
    return True


def claim():
    """Mark this process as the current speaker, interrupting the previous one."""
    stop()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def release():
    try:
        if int(PID_FILE.read_text()) == os.getpid():
            PID_FILE.unlink()
    except (OSError, ValueError):
        pass


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
