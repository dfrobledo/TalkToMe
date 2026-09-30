"""Configuration, and the protection of what makes Rachel yours.

Layers, lowest to highest: DEFAULTS → talktome.config.json (the project's
values, in git) → your config (outside the repository) → environment/.env.

Your config (your voice above all) lives outside the repository, in
%APPDATA%\\TalkToMe (Windows) or ~/.config/talktome, so no git operation, no
fresh clone and no rollback to an older version can touch it. Around it:
- every change is backed up first (the last BACKUPS copies);
- every voice you choose is remembered (voces.json), so if the config is
  ever lost she keeps her voice instead of falling back to the stand-in;
- the voice is also mirrored into .env, the one place every version of
  TalkToMe ever released reads it from: going back to an older version
  keeps her voice too.
The API key never leaves .env, which git ignores: it is never versioned.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("TALKTOME_STATE", Path.home() / ".talktome"))

DEFAULTS = {
    "enabled": True,
    "honorific": "señor",
    # Lily: velvety British female, a stand-in until `talktome design`
    # creates her own voice.
    "voice_id": "pFZP5JQG7iQjIQuC4Bku",
    # eleven_multilingual_v2: most natural Spanish.
    # eleven_flash_v2_5: ~75 ms latency, slightly less nuance.
    # eleven_v3: most expressive, understands [sighs], [dry] style tags.
    "model_id": "eleven_multilingual_v2",
    "language_code": "es",
    "voice_settings": {
        "stability": 0.4,
        "similarity_boost": 0.8,
        "style": 0.35,
        "use_speaker_boost": True,
        "speed": 0.97,
    },
    # auto: short replies in full, long ones only their spoken summary
    # (the opening paragraph). lead: always the summary. full: everything.
    "mode": "auto",
    "max_chars": 450,
    # The spoken summary covers the whole reply, so it gets more room.
    "summary_max_chars": 650,
    # "detalle": the rest of the last reply, narrated on demand.
    "detail_max_chars": 2500,
    # Layer 2: when a reply has no spoken summary, have Claude write one.
    # "claude" uses the Claude Code CLI on your plan; "off" disables it.
    "summarizer": "claude",
    # Chance that an idle reminder has Claude invent new ones afterwards
    # (0 turns it off), and how many invented lines to keep.
    "invent_chance": 0.2,
    "invented_max": 60,
    # With several terminals open, say which project Rachel speaks from:
    # "switch" when her voice jumps to another project, "always", or "off".
    "announce_project": "switch",
    # Folder name → spoken name, or {"name": ..., "voice_id": ..., ...}
    # for a project with its own name, voice or honorific.
    "projects": {},
    # Rachel says out loud what went wrong (her voice, or the system's when
    # ElevenLabs is the problem), at most once every few minutes per kind.
    "report_errors": True,
    "greet_on_start": True,
    "speak_notifications": True,
    "interrupt_on_prompt": True,
    # Dictation (talktome escucha): hold this key, speak, release to send.
    "listen_key": "F9",
    # Start listening in the background with Claude Code (Windows), and stop
    # once every session closed or after this long without any activity.
    "listen_on_start": True,
    "listen_idle_minutes": 120,
    "listen_min_seconds": 0.4,
    "listen_max_seconds": 120,
    # ElevenLabs Scribe; keyterms: words it should expect (names, jargon).
    "stt_model": "scribe_v2",
    "stt_keyterms": [],
    # Transcribe while you speak (Scribe v2 Realtime); batch Scribe if it fails.
    "stt_realtime": True,
    "stt_realtime_model": "scribe_v2_realtime",
    "stt_realtime_timeout": 5,
    # "Entendido, señor." the moment a dictation is sent.
    "voice_ack": True,
    # Company while Claude works (thinking sounds, what it is doing):
    # "voice" for turns started by dictation, "always", or "off".
    "narrate_progress": "voice",
    "cache_max_chars": 160,
    "player": "auto",
}


def config_path():
    """talktome.config.json, or the legacy jarvis.config.json if that is what exists."""
    if os.environ.get("TALKTOME_CONFIG"):
        return Path(os.environ["TALKTOME_CONFIG"])
    legacy = ROOT / "jarvis.config.json"
    current = ROOT / "talktome.config.json"
    return legacy if legacy.exists() and not current.exists() else current


def user_dir():
    """Where your own config lives: outside the repository, out of git's reach."""
    if os.environ.get("TALKTOME_USER_DIR"):
        return Path(os.environ["TALKTOME_USER_DIR"])
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "TalkToMe"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "talktome"


def user_path():
    return user_dir() / "config.json"


def history_path():
    return user_dir() / "voces.json"


def env_path():
    return Path(os.environ.get("TALKTOME_ENV_FILE", ROOT / ".env"))


BACKUPS = 10
# The block TalkToMe keeps in .env for older versions. This version reads
# your config instead, so it skips the block (and rewrites it when stale).
MIRROR_START = "# >>> TalkToMe: su voz, para que cualquier versión la use (no edite este bloque)"
MIRROR_END = "# <<< TalkToMe"
STAND_IN = DEFAULTS["voice_id"]  # Lily, until she has her own


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    """Write through a temporary file: a crash never leaves half a config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _merge(cfg, user):
    user = dict(user)
    settings = {**cfg["voice_settings"], **user.pop("voice_settings", {})}
    cfg.update(user)
    cfg["voice_settings"] = settings


def _env_text():
    try:
        raw = env_path().read_bytes()
    except OSError:
        return None
    # Windows editors may save with a BOM, and PowerShell's `>` writes UTF-16.
    return raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")


def _load_dotenv():
    text = _env_text()
    if text is None:
        return
    mirror = False
    for line in text.splitlines():
        line = line.strip()
        if line == MIRROR_START:
            mirror = True
        elif line == MIRROR_END:
            mirror = False
        elif not mirror and line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def mirror_block(voice_id, model_id=None):
    lines = [MIRROR_START, f"ELEVENLABS_VOICE_ID={voice_id}"]
    if model_id and model_id != DEFAULTS["model_id"]:
        lines.append(f"ELEVENLABS_MODEL_ID={model_id}")
    return lines + [MIRROR_END]


def sync_mirror(voice_id, model_id=None):
    """Keep the copy of your voice in .env up to date, leaving every other line
    (your API key above all) as it was. Written as plain UTF-8, which every
    version reads. Returns True if .env changed."""
    text = _env_text()
    kept, inside = [], False
    for line in (text or "").splitlines():
        if line.strip() == MIRROR_START:
            inside = True
        elif line.strip() == MIRROR_END:
            inside = False
        elif not inside:
            kept.append(line)
    new = "\n".join([*kept, *mirror_block(voice_id, model_id)]) + "\n"
    if text is not None and text.replace("\r\n", "\n") == new:
        return False
    path = env_path()
    if text is not None:
        backup = user_dir() / "respaldos" / f".env-{time.strftime('%Y%m%d-%H%M%S')}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(text, encoding="utf-8")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, path)
    return True


def voice_history():
    """Every voice you chose, oldest first: [{"voice_id", "name", "at"}]."""
    return _read_json(history_path(), [])


def remember_voice(voice_id, name=""):
    history = [v for v in voice_history() if v.get("voice_id") != voice_id]
    history.append({"voice_id": voice_id, "name": name, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    _write_json(history_path(), history)


def _customized(repo):
    """What the repository config holds that differs from the defaults: the
    user's own changes, from before their config moved out of the repository."""
    own = {k: v for k, v in repo.items() if k != "voice_settings" and DEFAULTS.get(k) != v}
    settings = {k: v for k, v in (repo.get("voice_settings") or {}).items()
                if DEFAULTS["voice_settings"].get(k) != v}
    if settings:
        own["voice_settings"] = settings
    return own


def _protect(repo):
    """Your config, moving it out of the repository the first time."""
    user = _read_json(user_path(), None)
    if user is None:
        user = _customized(repo)
        if user:
            _write_json(user_path(), user)
            if user.get("voice_id"):
                remember_voice(user["voice_id"], "desde talktome.config.json")
    return user or {}


def load():
    # A key already in the environment wins over .env: remember which one we use.
    from_env = bool(os.environ.get("ELEVENLABS_API_KEY"))
    _load_dotenv()
    cfg = json.loads(json.dumps(DEFAULTS))
    repo = _read_json(config_path(), {})
    _merge(cfg, repo)
    try:
        user = _protect(repo)
    except OSError:
        user = _read_json(user_path(), {})
    _merge(cfg, user)
    cfg["voice_healed"] = False
    if "voice_id" not in user and cfg["voice_id"] == STAND_IN:
        # Her voice went missing (a lost config, a reverted file): the
        # history remembers it. Choosing the stand-in on purpose is written
        # in your config, and respected.
        remembered = voice_history()
        if remembered:
            cfg["voice_id"], cfg["voice_healed"] = remembered[-1]["voice_id"], True
    if cfg["voice_id"] != STAND_IN or "voice_id" in user:
        try:
            sync_mirror(cfg["voice_id"], cfg["model_id"])
        except OSError:
            pass
    for key, env in (("voice_id", "ELEVENLABS_VOICE_ID"), ("model_id", "ELEVENLABS_MODEL_ID")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    cfg["api_key"] = os.environ.get("ELEVENLABS_API_KEY", "")
    cfg["api_key_source"] = "variable de entorno" if from_env else ".env"
    cfg["muted"] = (STATE_DIR / "muted").exists()
    return cfg


def backup():
    """Copy your config before changing it; keep the last BACKUPS copies."""
    path = user_path()
    if not path.exists():
        return None
    folder = user_dir() / "respaldos"
    folder.mkdir(parents=True, exist_ok=True)
    # Date for people, nanoseconds so they always sort in order.
    copy = folder / f"config-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns():020d}.json"
    copy.write_bytes(path.read_bytes())
    for old in sorted(folder.glob("config-*.json"))[:-BACKUPS]:
        old.unlink()
    return copy


def save_setting(key, value):
    """Change one of your settings (backed up first). Returns the config path."""
    backup()
    data = _read_json(user_path(), {})
    data[key] = value
    _write_json(user_path(), data)
    return user_path()


def save_voice_id(voice_id, name=""):
    """Make `voice_id` her voice: in your config, the history and the .env copy."""
    path = save_setting("voice_id", voice_id)
    remember_voice(voice_id, name)
    try:
        model = _read_json(user_path(), {}).get("model_id")
        sync_mirror(voice_id, model)
    except OSError:
        pass
    return path


def set_muted(muted):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    flag = STATE_DIR / "muted"
    if muted:
        flag.touch()
    elif flag.exists():
        flag.unlink()
