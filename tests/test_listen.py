"""Rachel listens: hold the key, speak, and the words go to Claude Code (no mic, no network)."""
import ctypes
import io
import json
import time
import unittest
from unittest import mock

from voice import hooks, listen, mic, realtime, stt
from voice.config import DEFAULTS
from voice.tts import TTSError


class FakeRecorder:
    def __init__(self, fail=None):
        self.fail, self.state = fail, "new"

    def start(self, on_chunk=None):
        if self.fail:
            raise mic.MicError(self.fail)
        self.state = "recording"
        if on_chunk:
            on_chunk(b"PCM1")
            on_chunk(b"PCM2")

    def stop(self, path):
        self.state = "saved"
        return b"RIFF-audio"

    def cancel(self):
        self.state = "cancelled"


class FakeDesk:
    """The key is held for `held` seconds of the fake clock; the focus may move meanwhile."""

    def __init__(self, held=2.0, window=7, moves_to=None, mic_fail=None):
        self.held, self.window, self.moves_to = held, window, moves_to
        self.rec = FakeRecorder(mic_fail)
        self.typed, self.clipboard, self.beeps = [], [], []

    def key_down(self):
        return self.clock.now < self.held

    def foreground(self):
        return self.window

    def recorder(self):
        return self.rec

    def type_text(self, text, window):
        if self.moves_to is not None and self.moves_to != window:
            return False
        self.typed.append((text, window))
        return True

    def copy(self, text):
        self.clipboard.append(text)

    def beep(self, kind):
        self.beeps.append(kind)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeStream:
    """Scribe Realtime stand-in: says `heard`, or fails with `fail`."""

    def __init__(self, heard=None, fail=None):
        self.heard, self.fail, self.fed, self.state = heard, fail, [], "open"

    def feed(self, pcm):
        self.fed.append(pcm)

    def finish(self, timeout):
        if self.fail:
            raise TTSError(self.fail)
        self.state = "finished"
        return self.heard

    def cancel(self):
        self.state = "cancelled"


def dictate(desk, heard="Revisa las pruebas del módulo de telemetría.", cfg=None, transcribe=None, stream=None):
    clock = Clock()
    desk.clock = clock
    out = []
    hush, acknowledge, report = mock.Mock(), mock.Mock(), mock.Mock()
    listener = listen.Listener(cfg or DEFAULTS, desk, transcribe=transcribe or (lambda audio, cfg: heard),
                               stream=lambda cfg: stream, hush=hush, acknowledge=acknowledge, report=report,
                               clock=clock, sleep=clock.sleep, out=out.append)
    with mock.patch("voice.listen.hooks.log"):
        text = listener.dictate()
    listener.acknowledged = acknowledge
    desk.reported = [c.args[0] for c in report.call_args_list]
    desk.listener = listener
    return text, hush, out


class ListenerTest(unittest.TestCase):
    def test_speech_is_typed_into_the_window_that_had_the_focus(self):
        desk = FakeDesk()
        text, stop, _ = dictate(desk)
        self.assertEqual(text, "Revisa las pruebas del módulo de telemetría.")
        self.assertEqual(desk.typed, [(text, 7)])
        self.assertEqual(desk.beeps, ["start"])
        stop.assert_called_once_with()  # pressing the key silences Rachel at once
        desk.listener.acknowledged.assert_called_once()  # "Entendido, señor."
        self.assertTrue(hooks.was_dictated(text))  # the prompt hook will know it was spoken

    def test_a_tap_is_not_a_dictation(self):
        desk = FakeDesk(held=0.1)
        text, stop, _ = dictate(desk, transcribe=lambda *a: self.fail("nothing to transcribe"))
        self.assertEqual((text, desk.typed, desk.rec.state), ("", [], "cancelled"))
        self.assertEqual(desk.beeps, ["start", "short"])  # so you know it was too short

    def test_nothing_said_types_nothing(self):
        desk = FakeDesk()
        text, _, _ = dictate(desk, heard=" (risas) ")
        self.assertEqual((text, desk.typed, desk.beeps), ("", [], ["start", "error"]))
        self.assertEqual(desk.reported, [])  # silence is not an error

    def test_calla_only_silences(self):
        desk = FakeDesk()
        text, stop, out = dictate(desk, heard="Cállate, Rachel.")
        self.assertEqual((text, desk.typed), ("", []))
        stop.assert_called_once_with()
        self.assertIn("Rachel calla", out[0])
        desk.listener.acknowledged.assert_not_called()

    def test_repite_goes_to_claude_code_where_its_hook_handles_it(self):
        desk = FakeDesk()
        dictate(desk, heard="Repite, por favor.")
        self.assertEqual(desk.typed, [("Repite, por favor.", 7)])

    def test_focus_moved_leaves_it_on_the_clipboard(self):
        desk = FakeDesk(moves_to=9)
        text, _, out = dictate(desk)
        self.assertEqual((text, desk.typed), ("", []))
        self.assertEqual(desk.clipboard, ["Revisa las pruebas del módulo de telemetría."])
        self.assertIn("portapapeles", out[0])
        self.assertEqual(desk.reported, ["clipboard"])

    def test_scribe_failure_is_reported_not_raised(self):
        def broken(audio, cfg):
            raise TTSError("ElevenLabs 401: invalid key")

        desk = FakeDesk()
        text, _, out = dictate(desk, transcribe=broken)
        self.assertEqual((text, desk.typed, desk.beeps[-1]), ("", [], "error"))
        self.assertIn("401", out[0])
        self.assertEqual(desk.reported, ["auth"])

    def test_no_microphone(self):
        desk = FakeDesk(mic_fail="micrófono (open): no hay dispositivo")
        text, _, out = dictate(desk)
        self.assertEqual((text, desk.beeps), ("", ["error"]))
        self.assertEqual(desk.reported, ["mic"])

    def test_realtime_text_wins_and_audio_streams_while_recording(self):
        desk, stream = FakeDesk(), FakeStream("Corre las pruebas.")
        text, _, _ = dictate(desk, stream=stream, transcribe=lambda *a: self.fail("batch not needed"))
        self.assertEqual(text, "Corre las pruebas.")
        self.assertEqual(stream.fed, [b"PCM1", b"PCM2"])

    def test_realtime_failure_falls_back_to_batch(self):
        desk, stream = FakeDesk(), FakeStream(fail="Scribe en tiempo real: auth_error")
        text, _, _ = dictate(desk, heard="Por lotes.", stream=stream)
        self.assertEqual(text, "Por lotes.")
        self.assertEqual(desk.reported, ["realtime"])  # it works, but she says it is slower

    def test_tap_cancels_the_stream(self):
        desk, stream = FakeDesk(held=0.1), FakeStream("x")
        dictate(desk, stream=stream)
        self.assertEqual(stream.state, "cancelled")

    def test_held_too_long_is_sent_at_the_limit(self):
        desk = FakeDesk(held=999)
        text, _, _ = dictate(desk, cfg={**DEFAULTS, "listen_max_seconds": 3})
        self.assertTrue(text)
        self.assertAlmostEqual(desk.clock.now, 3, delta=0.1)


class RealtimeTest(unittest.TestCase):
    def test_frames_round_trip(self):
        for size in (0, 5, 125, 126, 70000):
            payload = bytes(range(256)) * (size // 256) + bytes(size % 256)
            frame = realtime.encode_frame(payload, mask=b"\x01\x02\x03\x04")
            data = io.BytesIO(frame)
            fin, opcode, back = realtime.read_frame(data.read)
            self.assertEqual((fin, opcode, back), (True, realtime.OP_TEXT, payload))
            self.assertEqual(data.read(), b"")

    def test_url(self):
        cfg = {**DEFAULTS, "stt_keyterms": ["RockAvionics", "una frase demasiado larga para realtime"]}
        url = realtime.url(cfg)
        self.assertTrue(url.startswith("wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v2_realtime"))
        for part in ("audio_format=pcm_16000", "commit_strategy=manual", "language_code=es", "keyterms=RockAvionics"):
            self.assertIn(part, url)
        self.assertNotIn("demasiado", url)

    def test_stream(self):
        server = FakeSocket([{"message_type": "session_started"},
                             {"message_type": "partial_transcript", "text": "Corre las"},
                             {"message_type": "committed_transcript", "text": "Corre las pruebas."}])
        stream = realtime.Stream(DEFAULTS, connect=lambda: server)
        stream.feed(b"\x00\x01" * 10)
        self.assertEqual(stream.finish(timeout=2), "Corre las pruebas.")
        sent = [json.loads(m) for m in server.sent]
        self.assertEqual(sent[0]["message_type"], "input_audio_chunk")
        self.assertEqual((sent[0]["commit"], sent[0]["sample_rate"]), (False, 16000))
        self.assertTrue(sent[-1]["commit"])

    def test_stream_error(self):
        server = FakeSocket([{"message_type": "auth_error", "error": "invalid api key"}])
        stream = realtime.Stream(DEFAULTS, connect=lambda: server)
        with self.assertRaisesRegex(TTSError, "auth_error"):
            stream.finish(timeout=2)

    def test_stream_cannot_connect(self):
        def refuse():
            raise OSError("sin red")

        stream = realtime.Stream(DEFAULTS, connect=refuse)
        with self.assertRaisesRegex(TTSError, "sin red"):
            stream.finish(timeout=2)


class FakeSocket:
    """Answers with `replies` only once the commit arrives, like Scribe."""

    def __init__(self, replies):
        import queue

        self.replies, self.sent, self.inbox = replies, [], queue.Queue()
        if replies and replies[0]["message_type"].endswith("error"):
            self.inbox.put(json.dumps(replies[0]))

    def send(self, text):
        self.sent.append(text)
        if json.loads(text)["commit"]:
            for reply in self.replies:
                self.inbox.put(json.dumps(reply))

    def recv(self):
        return self.inbox.get(timeout=5)

    def close(self):
        self.inbox.put(None)


class StopWordsTest(unittest.TestCase):
    def test_stop_words(self):
        for said in ("Calla.", "¡Silencio!", "Rachel, cállate", "Ya basta", "shh"):
            self.assertTrue(hooks.is_stop(said), said)
        for said in ("calla los warnings del compilador", "para", "ya", "detalle"):
            self.assertFalse(hooks.is_stop(said), said)

    def test_typed_calla_never_reaches_claude(self):
        with mock.patch("voice.hooks.player.stop") as stop:
            decision = hooks.handle("prompt", {"prompt": "Calla", "session_id": "s1"}, DEFAULTS)
        self.assertEqual(decision["decision"], "block")
        stop.assert_called_once_with("s1")


class ScribeTest(unittest.TestCase):
    def test_request(self):
        sent = {}

        def urlopen(req, timeout):
            sent.update(url=req.full_url, body=req.data, type=req.headers["Content-type"], key=req.headers["Xi-api-key"])
            return io.BytesIO(json.dumps({"text": "hola", "language_code": "spa"}).encode())

        cfg = {**DEFAULTS, "api_key": "k", "stt_keyterms": ["RockAvionics", "Rachel"]}
        with mock.patch("voice.tts.urllib.request.urlopen", urlopen):
            self.assertEqual(stt.transcribe(b"WAVDATA", cfg), "hola")
        self.assertTrue(sent["url"].endswith("/speech-to-text"))
        self.assertTrue(sent["type"].startswith("multipart/form-data; boundary="))
        body = sent["body"].decode("latin-1")
        for part in ('name="model_id"\r\n\r\nscribe_v2', 'name="language_code"\r\n\r\nes',
                     'name="tag_audio_events"\r\n\r\nfalse', 'name="keyterms"\r\n\r\nRockAvionics',
                     'name="keyterms"\r\n\r\nRachel', 'filename="dictado.wav"', "WAVDATA"):
            self.assertIn(part, body)
        boundary = sent["type"].split("=", 1)[1]
        self.assertTrue(body.endswith(f"--{boundary}--\r\n"))

    def test_clean(self):
        self.assertEqual(stt.clean("  Hola,\n Rachel [music] (risas)  "), "Hola, Rachel")
        self.assertEqual(stt.clean("(silencio)"), "")
        self.assertEqual(stt.clean(" ... "), "")
        self.assertEqual(stt.clean("Corre f(x) con x = 2"), "Corre f(x) con x = 2")


class DeskTest(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(mic.vk_code("F9"), 0x78)
        self.assertEqual(mic.vk_code("f24"), 0x87)
        self.assertEqual(mic.vk_code("Scroll Lock"), 0x91)
        self.assertEqual(mic.vk_code("right_ctrl"), 0xA3)
        self.assertEqual(mic.vk_code("0x7B"), 0x7B)
        with self.assertRaises(ValueError):
            mic.vk_code("F25")

    def test_typing_accents_and_emoji(self):
        self.assertEqual(mic.utf16_units("ñá"), [0xF1, 0xE1])
        self.assertEqual(mic.utf16_units("🚀"), [0xD83D, 0xDE80])
        events = mic.key_events("sí", enter=True)
        self.assertEqual(len(events), 6)  # down+up per letter, then Enter
        self.assertEqual([e.ki.wScan for e in events[:4:2]], [ord("s"), ord("í")])
        self.assertEqual(events[-2].ki.wVk, mic.VK_RETURN)
        self.assertEqual(events[-1].ki.dwFlags, mic.KEYEVENTF_KEYUP)

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8, "layout of 64-bit Windows")
    def test_structures_match_win64_layout(self):
        self.assertEqual(ctypes.sizeof(mic.INPUT), 40)
        self.assertEqual(ctypes.sizeof(mic.WAVEHDR), 48)
        self.assertEqual(ctypes.sizeof(mic.KBDLLHOOKSTRUCT), 24)
        self.assertEqual(ctypes.sizeof(mic.WAVEFORMATEX), 18)

    def test_wav(self):
        import wave

        with wave.open(io.BytesIO(stt.wav_bytes(b"\x00\x00" * 1600))) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()), (16000, 1, 2, 1600))


if __name__ == "__main__":
    unittest.main()


class AutoStartTest(unittest.TestCase):
    CFG = {**DEFAULTS, "api_key": "k", "greet_on_start": False}

    def setUp(self):
        import shutil

        shutil.rmtree(hooks.OPEN_SESSIONS, ignore_errors=True)
        hooks.LISTEN_DOZED.unlink(missing_ok=True)

    def hook(self, event, session="s1", cfg=None, running=None):
        with mock.patch("voice.mic.available", return_value=True), \
                mock.patch("voice.listen.running", return_value=running), \
                mock.patch("voice.hooks.player.stop"), \
                mock.patch("voice.hooks.player.spawn") as spawn, mock.patch("voice.hooks._enqueue"):
            hooks.handle(event, {"session_id": session, "cwd": "", "prompt": "hola"}, cfg or self.CFG)
        return [c.args for c in spawn.call_args_list]

    def test_session_start_launches_the_listener_once(self):
        self.assertIn(("escucha", "--fondo"), self.hook("session"))
        self.assertNotIn(("escucha", "--fondo"), self.hook("session", running=1234))
        self.assertNotIn(("escucha", "--fondo"), self.hook("session", cfg={**self.CFG, "listen_on_start": False}))

    def test_open_sessions_keep_it_alive(self):
        self.hook("session", "a")
        self.hook("session", "b")
        self.assertTrue(hooks.claude_open())
        self.hook("end", "a")
        self.assertTrue(hooks.claude_open())
        self.hook("end", "b")
        self.assertTrue(hooks.claude_open())  # a minute of grace, in case one reopens
        self.assertFalse(hooks.claude_open(now=time.time() + 61))

    def test_idle_for_hours_lets_it_go(self):
        self.hook("session", "a")
        self.assertFalse(hooks.claude_open(idle_minutes=120, now=time.time() + 121 * 60))

    def test_next_prompt_wakes_a_dozing_listener(self):
        self.assertNotIn(("escucha", "--fondo"), self.hook("prompt"))
        hooks.LISTEN_DOZED.touch()
        self.assertIn(("escucha", "--fondo"), self.hook("prompt"))
        self.assertFalse(hooks.LISTEN_DOZED.exists())

    def test_run_leaves_when_claude_is_gone(self):
        desk = FakeDesk(held=0)
        desk.clock = Clock()
        listener = listen.Listener(DEFAULTS, desk, clock=desk.clock, sleep=desk.clock.sleep, out=lambda t: None)
        answers = iter([True, True, False])
        listener.run(alive=lambda: next(answers))
        self.assertAlmostEqual(desk.clock.now, 15, delta=0.1)  # checked every 5 s
