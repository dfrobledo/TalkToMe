"""Saying "Rachel": spotting her name, the conversation around it, and where the command goes."""
import unittest
from array import array
from datetime import datetime
from unittest import mock

from voice import alerts, hooks, lines, listen, persona, player, wake
from voice.config import DEFAULTS

CFG = {**DEFAULTS, "api_key": "k"}
LOUD = array("h", [6000, -6000] * 800).tobytes()
QUIET = bytes(3200)


class NameTest(unittest.TestCase):
    def test_find_wake(self):
        def found(text):
            return wake.find_wake(wake.normalize(text).split())

        self.assertEqual(found("Rachel, corre las pruebas"), (0, 1))
        self.assertEqual(found("Raquel"), (0, 1))
        self.assertEqual(found("oye Rachel"), (1, 2))
        self.assertEqual(found("hey ray chel abre el archivo"), (1, 3))
        self.assertIsNone(found("le dije a Raquel que venga"))  # a conversation, not a call
        self.assertIsNone(found("corre las pruebas"))
        self.assertIsNone(found(""))

    def test_strip_wake(self):
        self.assertEqual(wake.strip_wake("Rachel, corre las pruebas."), "Corre las pruebas.")
        self.assertEqual(wake.strip_wake("Oye, Raquel: ¿qué hora es en Tokio?"), "¿Qué hora es en Tokio?")
        self.assertEqual(wake.strip_wake("Rachel."), "")
        self.assertEqual(wake.strip_wake("Corre las pruebas."), "Corre las pruebas.")
        self.assertEqual(wake.strip_wake("Réichel, sí", ["reichel"]), "Sí")

    def test_cancel(self):
        for said in ("Nada.", "Nada, olvídalo.", "No importa", "cancela"):
            self.assertTrue(wake.is_cancel(said), said)
        self.assertFalse(wake.is_cancel("nada de pruebas hoy"))


class GateTest(unittest.TestCase):
    def test_opens_with_preroll_and_closes_after_hangover(self):
        gate = wake.Gate(hangover=0.5)
        for _ in range(5):
            self.assertEqual(gate.push(QUIET), ([], False))
        chunks, closed = gate.push(LOUD)
        self.assertEqual(chunks, [QUIET, QUIET, QUIET, LOUD])  # the start of the word is kept
        self.assertFalse(closed)
        results = [gate.push(QUIET) for _ in range(5)]
        self.assertEqual([closed for _, closed in results], [False, False, False, False, True])
        self.assertEqual(gate.push(QUIET), ([], False))

    def test_level(self):
        self.assertEqual(wake.level(QUIET), 0)
        self.assertAlmostEqual(wake.level(LOUD), 6000, delta=1)


class FakeSpotter:
    """Answers `script` in order: one (kind, text) per chunk fed; partial "" otherwise."""

    def __init__(self, script=(), final=""):
        self.script, self.final, self.resets, self.fed = list(script), final, 0, 0

    def feed(self, pcm):
        self.fed += 1
        return self.script.pop(0) if self.script else ("partial", "")

    def flush(self):
        final, self.final = self.final, ""
        return final

    def reset(self):
        self.resets += 1


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Conversation:
    def __init__(self, script=(), final="", heard="Rachel, corre las pruebas.", echo=False, cfg=CFG, stream=None):
        self.clock, self.said, self.delivered, self.stopped = Clock(), [], [], 0
        self.spotter = FakeSpotter(script, final)
        self.transcribed = []
        self.paused = False

        def transcribe(audio, cfg):
            self.transcribed.append(audio)
            return heard

        def stop():
            self.stopped += 1

        self.wake = wake.Wake(cfg, self.spotter, say=self.said.append,
                              deliver=lambda text, error=None: self.delivered.append(text or error),
                              transcribe=transcribe, stop_voice=stop, echo=lambda: echo,
                              stream=lambda cfg: stream, paused=lambda: self.paused, clock=self.clock)

    def play(self, *chunks):
        for chunk in chunks:
            self.wake.handle(chunk)
            self.clock.now += 0.1


class WakeTest(unittest.TestCase):
    def setUp(self):
        self.noon = mock.patch("voice.persona.datetime", wraps=datetime)
        self.noon.start()
        self.addCleanup(self.noon.stop)

    def test_in_one_breath(self):
        talk = Conversation([("partial", "raquel"), ("partial", "raquel corre"),
                             ("final", "raquel corre las pruebas")])
        talk.play(QUIET, QUIET, LOUD, LOUD, LOUD)
        self.assertEqual(talk.stopped, 1)  # silenced as soon as she heard her name
        self.assertEqual(talk.delivered, ["Corre las pruebas."])
        self.assertEqual(talk.said, [])  # no "¿Sí, señor?": the order came with the name
        self.assertTrue(talk.transcribed[0].startswith(b"RIFF"))

    def test_with_a_pause(self):
        talk = Conversation([("final", "raquel")], heard="Corre las pruebas.")
        talk.play(LOUD)
        wake_lines = {persona._fill(t, "señor") for t, _, _ in lines.WAKE}
        self.assertIn(talk.said[0], wake_lines)
        self.assertEqual(talk.wake.state, "listening")
        talk.play(*[QUIET] * 5, *[LOUD] * 10, *[QUIET] * 13)
        self.assertEqual(talk.delivered, ["Corre las pruebas."])
        self.assertEqual(talk.wake.state, "asleep")

    def test_answer_right_as_the_room_goes_quiet(self):
        # Her name is the last word before the gate closes: she must still wait for the order.
        script = [("partial", "raquel")] + [("partial", "")] * 19 + [("final", "raquel")]
        talk = Conversation(script, heard="Abre el archivo.")
        talk.play(LOUD, *[QUIET] * 20)
        self.assertEqual(talk.wake.state, "listening")
        talk.play(*[LOUD] * 5, *[QUIET] * 13)
        self.assertEqual(talk.delivered, ["Abre el archivo."])

    def test_called_then_silence(self):
        talk = Conversation([("final", "rachel")])
        talk.play(LOUD, *[QUIET] * 62)
        timeouts = {persona._fill(t, "señor") for t, _, _ in lines.WAKE_TIMEOUT}
        self.assertIn(talk.said[-1], timeouts)
        self.assertEqual((talk.delivered, talk.transcribed), ([], []))

    def test_never_mind(self):
        talk = Conversation([("final", "raquel")], heard="Nada, olvídalo.")
        talk.play(LOUD, *[LOUD] * 5, *[QUIET] * 13)
        cancels = {persona._fill(t, "señor") for t, _, _ in lines.WAKE_CANCEL}
        self.assertIn(talk.said[-1], cancels)
        self.assertEqual(talk.delivered, [])

    def test_calla_needs_no_transcription(self):
        talk = Conversation([("partial", "raquel"), ("final", "raquel calla")])
        talk.play(LOUD, LOUD)
        self.assertEqual((talk.stopped, talk.transcribed, talk.delivered), (1, [], []))

    def test_her_name_in_a_conversation_is_not_a_call(self):
        talk = Conversation([("partial", "le dije a raquel"), ("final", "le dije a raquel que venga")])
        talk.play(LOUD, LOUD)
        self.assertEqual((talk.stopped, talk.said, talk.delivered), (0, [], []))

    def test_her_own_voice_does_not_wake_her(self):
        talk = Conversation([("partial", "rachel"), ("final", "rachel corre")], echo=True)
        talk.play(LOUD, LOUD)
        self.assertEqual((talk.stopped, talk.delivered), (0, []))

    def test_utterance_ends_when_the_room_goes_quiet(self):
        talk = Conversation([("partial", "raquel corre las pruebas")], final="raquel corre las pruebas")
        talk.play(LOUD, *[QUIET] * 25)
        self.assertEqual(talk.delivered, ["Corre las pruebas."])

    def test_the_key_takes_the_microphone(self):
        talk = Conversation([("final", "raquel")])
        talk.play(LOUD)
        talk.paused = True
        talk.play(LOUD, LOUD)
        self.assertEqual(talk.wake.state, "asleep")
        self.assertEqual(talk.delivered, [])

    def test_realtime_stream_while_listening(self):
        stream = mock.Mock()
        stream.finish.return_value = "Abre el archivo."
        talk = Conversation([("final", "raquel")], stream=stream)
        talk.play(LOUD, *[LOUD] * 5, *[QUIET] * 13)
        self.assertEqual(talk.delivered, ["Abre el archivo."])
        self.assertEqual(talk.transcribed, [])  # the stream had it already
        self.assertGreater(stream.feed.call_count, 10)

    def test_one_breath_streams_from_the_moment_she_hears_her_name(self):
        stream = mock.Mock()
        stream.finish.return_value = "Rachel, corre las pruebas."
        talk = Conversation([("partial", "raquel"), ("partial", "raquel corre"),
                             ("final", "raquel corre las pruebas")], stream=stream)
        talk.play(QUIET, LOUD, LOUD, LOUD)
        self.assertEqual(talk.delivered, ["Corre las pruebas."])
        self.assertEqual(talk.transcribed, [])
        self.assertGreaterEqual(stream.feed.call_count, 3)  # the start of the utterance included

    def test_stock_lines_cover_her_quick_answers(self):
        stock = persona.stock_lines("señor")
        for bank in (lines.WAKE, lines.WAKE_TIMEOUT, lines.WAKE_CANCEL, lines.ACKS):
            for text, _, _ in bank:
                self.assertIn(persona._fill(text, "señor"), stock)
        self.assertFalse(any("[" in text for text in stock))
        self.assertTrue(any("[" in text for text in persona.stock_lines("señor", expressive=True)))

    def test_scribe_failure_is_reported(self):
        from voice.tts import TTSError

        talk = Conversation([("final", "raquel corre")])
        talk.wake.transcribe = mock.Mock(side_effect=TTSError("ElevenLabs 401: invalid_api_key"))
        talk.play(LOUD)
        self.assertIsInstance(talk.delivered[0], TTSError)

    def test_flavor(self):
        flavored = {persona._fill(t, "señor") for t, level, _ in lines.WAKE if level == 2}
        noon = datetime(2026, 9, 30, 12, 0)
        said = {persona.wake("señor", flavor=True, now=noon) for _ in range(20)}
        self.assertTrue(said <= flavored)
        self.assertTrue(all(len(persona._fill(t, "señor")) <= DEFAULTS["cache_max_chars"]
                            for bank in (lines.WAKE, lines.WAKE_TIMEOUT, lines.WAKE_CANCEL) for t, _, _ in bank))


class FakeDesk:
    def __init__(self, front=1, alive=(), refuse=False):
        self.front, self.alive_windows, self.refuse = front, set(alive), refuse
        self.typed, self.clipboard = [], []

    def foreground(self):
        return self.front

    def alive(self, window):
        return window in self.alive_windows

    def type_text(self, text, window):
        if self.refuse:
            return False
        self.typed.append((text, window))
        return True

    def copy(self, text):
        self.clipboard.append(text)


class DeliverTest(unittest.TestCase):
    def deliver(self, desk, windows, text="Corre las pruebas."):
        report, ack = mock.Mock(), mock.Mock()
        with mock.patch("voice.listen.hooks.session_windows", return_value=windows), \
                mock.patch("voice.listen.hooks.log"):
            listen.deliverer(CFG, desk, out=lambda t: None, acknowledge=ack, report=report)(text)
        return [c.args[0] for c in report.call_args_list], ack.called

    def test_to_the_terminal_in_front(self):
        desk = FakeDesk(front=22, alive={11, 22})
        self.assertEqual(self.deliver(desk, [(11, 9), (22, 5)]), ([], True))
        self.assertEqual(desk.typed, [("Corre las pruebas.", 22)])
        self.assertTrue(hooks.was_dictated("Corre las pruebas."))  # it gets company, like a dictation

    def test_else_to_the_one_used_last(self):
        desk = FakeDesk(front=99, alive={11, 22})
        self.deliver(desk, [(33, 10), (11, 9), (22, 5)])  # 33 was closed
        self.assertEqual(desk.typed, [("Corre las pruebas.", 11)])

    def test_no_terminal(self):
        desk = FakeDesk(front=99)
        self.assertEqual(self.deliver(desk, []), (["no_target"], False))
        self.assertEqual(desk.clipboard, ["Corre las pruebas."])

    def test_windows_refuses_the_focus(self):
        desk = FakeDesk(front=99, alive={11}, refuse=True)
        self.assertEqual(self.deliver(desk, [(11, 1)]), (["focus"], False))
        self.assertEqual(desk.clipboard, ["Corre las pruebas."])

    def test_error_is_reported(self):
        from voice.tts import TTSError

        report = mock.Mock()
        listen.deliverer(CFG, FakeDesk(), report=report)(None, error=TTSError("Sin conexión con ElevenLabs"))
        self.assertEqual(report.call_args.args[0], "network")


class HubTest(unittest.TestCase):
    def test_key_borrows_the_open_microphone(self):
        hub = wake.Hub(mock.Mock())
        hub._chunk(b"a")
        tap = hub.recorder_for_key()
        fed = []
        tap.start(on_chunk=fed.append)
        hub._chunk(b"\x01\x00")
        hub._chunk(b"\x02\x00")
        self.assertIs(hub.tap, tap)
        wav = tap.stop()
        self.assertIsNone(hub.tap)
        self.assertEqual(fed, [b"\x01\x00", b"\x02\x00"])
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertEqual(hub.queue.qsize(), 3)  # the name spotter got everything too
        hub.drain()
        self.assertEqual(hub.queue.qsize(), 0)


class EngineTest(unittest.TestCase):
    def test_auto_needs_vosk_and_model(self):
        with mock.patch.dict("sys.modules", {"vosk": None}):
            ready, why = wake.engine(CFG)
            self.assertFalse(ready)
            self.assertIn("Vosk", why)
            self.assertFalse(wake.enabled(CFG))
            self.assertFalse(wake.enabled({**CFG, "wake": False}))

    def test_session_windows_newest_first(self):
        import shutil
        import time

        shutil.rmtree(hooks.OPEN_SESSIONS, ignore_errors=True)
        hooks.OPEN_SESSIONS.mkdir(parents=True)
        for session, window, age in (("a", 11, 50), ("b", 22, 10), ("gone", 33, 1)):
            folder = player.session_dir(session)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "window").write_text(str(window))
            import os

            os.utime(folder / "window", (time.time() - age, time.time() - age))
            if session != "gone":
                (hooks.OPEN_SESSIONS / session).touch()
        self.assertEqual([w for w, _ in hooks.session_windows()], [22, 11])

    def test_new_alerts_name_what_to_check(self):
        for kind in ("focus", "no_target", "wake"):
            self.assertRegex(alerts.line(kind, CFG), r"^(Falla|Falta)")


if __name__ == "__main__":
    unittest.main()
