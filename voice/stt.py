"""ElevenLabs speech-to-text (Scribe): what the user said, as text (stdlib only)."""
import io
import json
import re
import uuid
import wave

from .tts import TTSError, _request

# Scribe adds tags such as "(risas)" or "[music]" for sounds that are not words.
AUDIO_EVENT = re.compile(r"(?<!\w)[(\[][^()\[\]]{1,40}[)\]]")


def multipart(fields, files):
    """multipart/form-data body. `fields`: (name, value) pairs, repeated names allowed;
    `files`: (name, filename, bytes). Returns (body, content_type)."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, filename, data in files:
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n")
        parts.append(head.encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(audio, cfg, filename="dictado.wav"):
    """Text of a recording (any format ElevenLabs reads: wav, mp3, m4a...)."""
    fields = [
        ("model_id", cfg.get("stt_model", "scribe_v2")),
        ("tag_audio_events", "false"),
        ("timestamps_granularity", "none"),
    ]
    if cfg.get("language_code"):
        fields.append(("language_code", cfg["language_code"]))
    # Words Scribe should expect: project names, jargon, people.
    fields += [("keyterms", term) for term in cfg.get("stt_keyterms") or []]
    body, content_type = multipart(fields, [("file", filename, audio)])
    with _request("/speech-to-text", cfg, method="POST", data=body, content_type=content_type, timeout=60) as resp:
        return json.load(resp).get("text", "")


def wav_bytes(pcm, rate=16000):
    """16-bit mono PCM wrapped as a WAV file."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def clean(text):
    """One line of plain words, ready to type as a prompt; "" if nothing was said."""
    text = AUDIO_EVENT.sub(" ", text or "")
    text = " ".join(text.split())
    return text if re.search(r"\w", text) else ""


__all__ = ["TTSError", "clean", "multipart", "transcribe", "wav_bytes"]
