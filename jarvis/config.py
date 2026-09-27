"""Configuration: jarvis.config.json + .env (API key) + environment overrides."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("TALKTOME_STATE", Path.home() / ".talktome"))

DEFAULTS = {
    "enabled": True,
    "honorific": "señor",
    # George: warm, calm British male. Change with `talktome voices`.
    "voice_id": "JBFqnCBsd6RMkjVDRZzb",
    # eleven_multilingual_v2: most natural Spanish.
    # eleven_flash_v2_5: ~75 ms latency, slightly less nuance.
    # eleven_v3: most expressive, understands [sighs], [dry] style tags.
    "model_id": "eleven_multilingual_v2",
    "language_code": "es",
    "voice_settings": {
        "stability": 0.45,
        "similarity_boost": 0.8,
        "style": 0.3,
        "use_speaker_boost": True,
        "speed": 1.0,
    },
    # auto: short replies in full, long ones only their opening paragraph.
    # lead: always the opening paragraph. full: everything (up to max_chars).
    "mode": "auto",
    "max_chars": 450,
    "greet_on_start": True,
    "speak_notifications": True,
    "interrupt_on_prompt": True,
    "cache_max_chars": 160,
    "player": "auto",
}


def _load_dotenv():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load():
    _load_dotenv()
    cfg = json.loads(json.dumps(DEFAULTS))
    path = Path(os.environ.get("TALKTOME_CONFIG", ROOT / "jarvis.config.json"))
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
        settings = {**cfg["voice_settings"], **user.pop("voice_settings", {})}
        cfg.update(user)
        cfg["voice_settings"] = settings
    for key, env in (("voice_id", "ELEVENLABS_VOICE_ID"), ("model_id", "ELEVENLABS_MODEL_ID")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    cfg["api_key"] = os.environ.get("ELEVENLABS_API_KEY", "")
    cfg["muted"] = (STATE_DIR / "muted").exists()
    return cfg


def set_muted(muted):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    flag = STATE_DIR / "muted"
    if muted:
        flag.touch()
    elif flag.exists():
        flag.unlink()
