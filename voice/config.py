"""Configuration: talktome.config.json + .env (API key) + environment overrides."""
import json
import os
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
    "greet_on_start": True,
    "speak_notifications": True,
    "interrupt_on_prompt": True,
    # Dictation (talktome escucha): hold this key, speak, release to send.
    "listen_key": "F9",
    "listen_min_seconds": 0.4,
    "listen_max_seconds": 120,
    # ElevenLabs Scribe; keyterms: words it should expect (names, jargon).
    "stt_model": "scribe_v2",
    "stt_keyterms": [],
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


def _load_dotenv():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    raw = env_file.read_bytes()
    # Windows editors may save with a BOM, and PowerShell's `>` writes UTF-16.
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load():
    # A key already in the environment wins over .env: remember which one we use.
    from_env = bool(os.environ.get("ELEVENLABS_API_KEY"))
    _load_dotenv()
    cfg = json.loads(json.dumps(DEFAULTS))
    path = config_path()
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
        settings = {**cfg["voice_settings"], **user.pop("voice_settings", {})}
        cfg.update(user)
        cfg["voice_settings"] = settings
    for key, env in (("voice_id", "ELEVENLABS_VOICE_ID"), ("model_id", "ELEVENLABS_MODEL_ID")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    cfg["api_key"] = os.environ.get("ELEVENLABS_API_KEY", "")
    cfg["api_key_source"] = "variable de entorno" if from_env else ".env"
    cfg["muted"] = (STATE_DIR / "muted").exists()
    return cfg


def save_voice_id(voice_id):
    """Write the voice into the config file, keeping the user's other keys."""
    path = config_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["voice_id"] = voice_id
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def set_muted(muted):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    flag = STATE_DIR / "muted"
    if muted:
        flag.touch()
    elif flag.exists():
        flag.unlink()
