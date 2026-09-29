"""ElevenLabs text-to-speech client (stdlib only)."""
import hashlib
import io
import json
import os
import urllib.error
import urllib.request
import wave

from .config import STATE_DIR

API = os.environ.get("ELEVENLABS_API_BASE", "https://api.elevenlabs.io/v1")
# Models that accept language enforcement; others reject the parameter.
LANGUAGE_MODELS = {"eleven_flash_v2_5", "eleven_turbo_v2_5"}
PCM_RATE = 24000


class TTSError(RuntimeError):
    pass


def _request(path, cfg, body=None, method="GET", data=None, content_type="application/json", timeout=30):
    """Call ElevenLabs: `body` goes as JSON, `data` as raw bytes of `content_type`."""
    if not cfg.get("api_key"):
        raise TTSError("Falta ELEVENLABS_API_KEY (ponla en .env).")
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={"xi-api-key": cfg["api_key"], "Content-Type": content_type},
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise TTSError(f"ElevenLabs {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise TTSError(f"Sin conexión con ElevenLabs: {e.reason}") from e


def _body(text, cfg):
    body = {"text": text, "model_id": cfg["model_id"], "voice_settings": cfg["voice_settings"]}
    if cfg.get("language_code") and cfg["model_id"] in LANGUAGE_MODELS:
        body["language_code"] = cfg["language_code"]
    return body


def stream(text, cfg, output_format="mp3_44100_128"):
    """Yield audio chunks as ElevenLabs generates them."""
    path = f"/text-to-speech/{cfg['voice_id']}/stream?output_format={output_format}"
    resp = _request(path, cfg, _body(text, cfg), "POST")
    with resp:
        while True:
            chunk = resp.read(4096)
            if not chunk:
                return
            yield chunk


def wav(text, cfg):
    """Full utterance as WAV bytes, for players that cannot stream."""
    pcm = b"".join(stream(text, cfg, f"pcm_{PCM_RATE}"))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(PCM_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def cache_path(text, cfg, ext):
    key = json.dumps([text, cfg["voice_id"], cfg["model_id"], cfg["voice_settings"]], sort_keys=True)
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return STATE_DIR / "cache" / f"{digest}.{ext}"


def design(description, sample_text, cfg):
    """Voice Design: generate candidate voices from a text description."""
    body = {"voice_description": description, "text": sample_text, "model_id": "eleven_ttv_v3"}
    with _request("/text-to-voice/design?output_format=mp3_44100_128", cfg, body, "POST") as resp:
        return json.load(resp).get("previews", [])


def save_voice(name, description, generated_voice_id, cfg):
    """Keep a designed preview in the user's voice library; returns its voice_id."""
    body = {"voice_name": name, "voice_description": description, "generated_voice_id": generated_voice_id}
    with _request("/text-to-voice", cfg, body, "POST") as resp:
        return json.load(resp)["voice_id"]


def voices(cfg):
    with _request("/voices", cfg) as resp:
        return json.load(resp).get("voices", [])


def subscription(cfg):
    with _request("/user/subscription", cfg) as resp:
        return json.load(resp)
