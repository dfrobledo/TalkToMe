"""Rachel listens: hold the key, speak, and the words go to Claude Code (no mic, no network)."""
import ctypes
import io
import json
import unittest
from unittest import mock

from voice import hooks, listen, mic, stt
from voice.config import DEFAULTS
from voice.tts import TTSError


class FakeRecorder:
    def __init__(self, fail=None):
        self.fail, self.state = fail, "new"

    def start(self):
        if self.fail:
            raise mic.MicError(self.fail)
        self.state = "recording"

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


def dictate(desk, heard="Revisa las pruebas del módulo de telemetría.", cfg=None, transcribe=None):
    clock = Clock()
    desk.clock = clock
    out = []
    listener = listen.Listener(cfg or DEFAULTS, desk, transcribe=transcribe or (lambda audio, cfg: heard),
                               clock=clock, sleep=clock.sleep, out=out.append)
    with mock.patch("voice.listen.player.stop") as stop, mock.patch("voice.listen.hooks.log"):
        text = listener.dictate()
    return text, stop, out


class ListenerTest(unittest.TestCase):
    def test_speech_is_typed_into_the_window_that_had_the_focus(self):
        desk = FakeDesk()
        text, stop, _ = dictate(desk)
        self.assertEqual(text, "Revisa las pruebas del módulo de telemetría.")
        self.assertEqual(desk.typed, [(text, 7)])
        self.assertEqual(desk.beeps, ["start"])
        stop.assert_called_once_with()  # pressing the key silences Rachel at once

    def test_a_tap_is_not_a_dictation(self):
        desk = FakeDesk(held=0.1)
        text, stop, _ = dictate(desk, transcribe=lambda *a: self.fail("nothing to transcribe"))
        self.assertEqual((text, desk.typed, desk.rec.state), ("", [], "cancelled"))

    def test_nothing_said_types_nothing(self):
        desk = FakeDesk()
        text, _, _ = dictate(desk, heard=" (risas) ")
        self.assertEqual((text, desk.typed, desk.beeps), ("", [], ["start", "error"]))

    def test_calla_only_silences(self):
        desk = FakeDesk()
        text, stop, out = dictate(desk, heard="Cállate, Rachel.")
        self.assertEqual((text, desk.typed), ("", []))
        stop.assert_called_once_with()
        self.assertIn("Rachel calla", out[0])

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

    def test_scribe_failure_is_reported_not_raised(self):
        def broken(audio, cfg):
            raise TTSError("ElevenLabs 401: invalid key")

        desk = FakeDesk()
        text, _, out = dictate(desk, transcribe=broken)
        self.assertEqual((text, desk.typed, desk.beeps[-1]), ("", [], "error"))
        self.assertIn("401", out[0])

    def test_no_microphone(self):
        desk = FakeDesk(mic_fail="micrófono (open): no hay dispositivo")
        text, _, out = dictate(desk)
        self.assertEqual((text, desk.beeps), ("", ["error"]))

    def test_held_too_long_is_sent_at_the_limit(self):
        desk = FakeDesk(held=999)
        text, _, _ = dictate(desk, cfg={**DEFAULTS, "listen_max_seconds": 3})
        self.assertTrue(text)
        self.assertAlmostEqual(desk.clock.now, 3, delta=0.1)


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
    def test_input_matches_win64_layout(self):
        self.assertEqual(ctypes.sizeof(mic.INPUT), 40)


if __name__ == "__main__":
    unittest.main()
