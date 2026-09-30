"""Scribe v2 Realtime: transcribe while the user is still speaking (stdlib only).

The microphone streams 100 ms PCM chunks into a WebSocket as they are
recorded; releasing the key only commits what is already there, so the
text is ready a moment later instead of after a whole upload. Anything
going wrong raises TTSError, and the dictation falls back to batch Scribe.
"""
import base64
import json
import os
import queue
import socket
import ssl
import struct
import threading
import urllib.parse

from .tts import TTSError

HOST = "api.elevenlabs.io"
RATE = 16000
OP_CONT, OP_TEXT, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x8, 0x9, 0xA
ERRORS = {"error", "auth_error", "quota_exceeded", "commit_throttled", "transcriber_error", "unaccepted_terms",
          "rate_limited", "input_error", "invalid_request", "queue_overflow", "resource_exhausted"}
_COMMIT, _CANCEL = object(), object()


def encode_frame(payload, opcode=OP_TEXT, mask=None):
    """One final WebSocket frame. Clients must mask: `mask` is 4 random bytes."""
    mask = os.urandom(4) if mask is None else mask
    size = len(payload)
    head = bytes([0x80 | opcode])
    if size < 126:
        head += bytes([0x80 | size])
    elif size < 1 << 16:
        head += bytes([0x80 | 126]) + struct.pack(">H", size)
    else:
        head += bytes([0x80 | 127]) + struct.pack(">Q", size)
    return head + mask + _mask(payload, mask)


def _mask(data, mask):
    if not data:
        return b""
    key = int.from_bytes((mask * (len(data) // 4 + 1))[:len(data)], "big")
    return (int.from_bytes(data, "big") ^ key).to_bytes(len(data), "big")


def read_frame(read):
    """(fin, opcode, payload) of the next frame; `read(n)` returns exactly n bytes."""
    first, second = read(2)
    size = second & 0x7F
    if size == 126:
        size = struct.unpack(">H", read(2))[0]
    elif size == 127:
        size = struct.unpack(">Q", read(8))[0]
    mask = read(4) if second & 0x80 else None
    payload = read(size) if size else b""
    return bool(first & 0x80), first & 0x0F, _mask(payload, mask) if mask else payload


class WebSocket:
    """Just enough of a WebSocket client for Scribe: text frames, ping, close."""

    def __init__(self, url, headers, timeout=10):
        parts = urllib.parse.urlsplit(url)
        raw = socket.create_connection((parts.hostname, parts.port or 443), timeout=timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=parts.hostname)
        self.rfile = self.sock.makefile("rb")
        self.lock = threading.Lock()
        key = base64.b64encode(os.urandom(16)).decode()
        lines = [f"GET {parts.path}?{parts.query} HTTP/1.1", f"Host: {parts.hostname}", "Upgrade: websocket",
                 "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
        lines += [f"{name}: {value}" for name, value in headers.items()]
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        status = self.rfile.readline().decode(errors="replace").strip()
        while self.rfile.readline() not in (b"\r\n", b"\n", b""):
            pass
        if " 101 " not in f"{status} ":
            self.close()
            raise TTSError(f"Scribe en tiempo real rechazó la conexión: {status}")
        self.sock.settimeout(None)

    def _read(self, n):
        data = self.rfile.read(n)
        if len(data) < n:
            raise OSError("conexión cerrada")
        return data

    def send(self, text, opcode=OP_TEXT):
        frame = encode_frame(text.encode() if isinstance(text, str) else text, opcode)
        with self.lock:
            self.sock.sendall(frame)

    def recv(self):
        """Next text message, or None once the server closes."""
        parts = []
        while True:
            fin, opcode, payload = read_frame(self._read)
            if opcode == OP_PING:
                self.send(payload, OP_PONG)
            elif opcode == OP_CLOSE:
                return None
            elif opcode in (OP_TEXT, OP_CONT):
                parts.append(payload)
                if fin:
                    return b"".join(parts).decode("utf-8", errors="replace")

    def close(self):
        try:
            self.send(b"", OP_CLOSE)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def url(cfg):
    params = [("model_id", cfg.get("stt_realtime_model", "scribe_v2_realtime")),
              ("audio_format", f"pcm_{RATE}"), ("commit_strategy", "manual")]
    if cfg.get("language_code"):
        params.append(("language_code", cfg["language_code"]))
    # The realtime model takes up to 50 keyterms of 20 characters at most.
    params += [("keyterms", term) for term in (cfg.get("stt_keyterms") or []) if len(term) <= 20][:50]
    base = os.environ.get("ELEVENLABS_WS_BASE", f"wss://{HOST}")
    return f"{base}/v1/speech-to-text/realtime?{urllib.parse.urlencode(params)}"


class Stream:
    """One dictation: connects in the background while the microphone already records.

    `feed(pcm)` from the recorder, then `finish()` for the text or `cancel()`.
    """

    def __init__(self, cfg, connect=None):
        self.cfg = cfg
        self.connect = connect or (lambda: WebSocket(url(cfg), {"xi-api-key": cfg.get("api_key", "")}))
        self.pending = queue.Queue()
        self.texts, self.error = [], None
        self.committed = threading.Event()
        self.commit_sent = False
        threading.Thread(target=self._run, daemon=True).start()

    def feed(self, pcm):
        self.pending.put(pcm)

    def finish(self, timeout=5.0):
        """Everything said, once Scribe commits it. Raises TTSError on failure or timeout."""
        self.pending.put(_COMMIT)
        if not self.committed.wait(timeout):
            self.pending.put(_CANCEL)
            raise TTSError(f"Scribe en tiempo real no respondió en {timeout:.0f} s")
        if self.error:
            raise self.error
        return " ".join(t for t in self.texts if t).strip()

    def cancel(self):
        self.pending.put(_CANCEL)

    def _fail(self, error):
        self.error = error if isinstance(error, TTSError) else TTSError(f"Scribe en tiempo real: {error}")
        self.committed.set()

    def _run(self):
        ws = None
        try:
            ws = self.connect()
            threading.Thread(target=self._listen, args=(ws,), daemon=True).start()
            while True:
                item = self.pending.get()
                if item is _CANCEL:
                    return
                if item is _COMMIT:
                    self.commit_sent = True  # before sending: the answer can be that quick
                    self._send(ws, b"", commit=True)
                    self.committed.wait(30)
                    return
                # While connecting, audio piles up: send it in one go.
                chunks, stop = [item], None
                while not self.pending.empty():
                    more = self.pending.get()
                    if more is _COMMIT or more is _CANCEL:
                        stop = more
                        break
                    chunks.append(more)
                self._send(ws, b"".join(chunks))
                if stop is not None:
                    self.pending.put(stop)
        except (OSError, TTSError, ValueError) as e:
            self._fail(e)
        finally:
            if ws:
                ws.close()

    def _send(self, ws, pcm, commit=False):
        ws.send(json.dumps({"message_type": "input_audio_chunk", "audio_base_64": base64.b64encode(pcm).decode(),
                            "commit": commit, "sample_rate": RATE}))

    def _listen(self, ws):
        try:
            while True:
                raw = ws.recv()
                if raw is None:
                    return self._fail(TTSError("Scribe en tiempo real cerró la conexión"))
                message = json.loads(raw)
                kind = message.get("message_type", "")
                if kind == "committed_transcript":
                    self.texts.append(message.get("text", ""))
                    if self.commit_sent:
                        self.committed.set()
                        return
                elif kind in ERRORS:
                    detail = message.get("error") or message.get("message") or kind
                    return self._fail(TTSError(f"Scribe en tiempo real: {kind}: {detail}"))
        except (OSError, ValueError) as e:
            if not self.committed.is_set():
                self._fail(e)
