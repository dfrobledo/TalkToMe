"""Rachel reports errors out loud: the right line, not too often, offline when ElevenLabs is the problem."""
import unittest
from unittest import mock

from voice import alerts, cli, mic
from voice.config import DEFAULTS
from voice.tts import TTSError

CFG = {**DEFAULTS, "api_key": "k"}


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        cases = {
            'ElevenLabs 401: {"detail":{"status":"invalid_api_key"}}': "auth",
            'ElevenLabs 401: {"detail":{"status":"quota_exceeded"}}': "quota",
            "Scribe en tiempo real: auth_error: invalid api key": "auth",
            "Falta ELEVENLABS_API_KEY (ponla en .env).": "no_key",
            "Sin conexión con ElevenLabs: [Errno 11001] getaddrinfo failed": "network",
            "Scribe en tiempo real no respondió en 5 s": "network",
            "micrófono (abrir): No hay ningún dispositivo": "mic",
            "Windows no dejó escribir en esa ventana (¿terminal como administrador?": "elevated",
            "ElevenLabs 500: internal error": "crash",
            "No hay reproductor de audio: instala mpv o ffmpeg.": "player",
        }
        for message, kind in cases.items():
            self.assertEqual(alerts.classify(TTSError(message)), kind, message)
        self.assertEqual(alerts.classify(ConnectionResetError()), "network")
        self.assertEqual(alerts.classify(mic.MicError("micrófono (grabar): error")), "mic")
        self.assertEqual(alerts.classify(KeyError("x")), "crash")

    def test_every_kind_has_a_line(self):
        for kind in alerts.LINES:
            text = alerts.line(kind, CFG)
            self.assertLessEqual(len(text), DEFAULTS["cache_max_chars"], text)
            self.assertNotIn("{", text)


class ReportTest(unittest.TestCase):
    def setUp(self):
        alerts.STATE_FILE.unlink(missing_ok=True)

    def report(self, kind, cfg=CFG):
        with mock.patch("voice.alerts.system_say", return_value=True) as offline, \
                mock.patch("voice.hooks._enqueue") as enqueue, mock.patch("voice.hooks.log"):
            said = alerts.report(kind, cfg, "detalle")
        return said, offline, enqueue

    def test_her_voice_for_local_problems(self):
        said, offline, enqueue = self.report("mic")
        self.assertTrue(said)
        offline.assert_not_called()
        self.assertEqual(enqueue.call_args.args[1]["text"], alerts.line("mic", CFG))

    def test_system_voice_when_elevenlabs_is_the_problem(self):
        for kind in ("auth", "quota", "network", "no_key"):
            with mock.patch("voice.alerts.player.cached", return_value=False):
                said, offline, enqueue = self.report(kind)
            offline.assert_called_once_with(alerts.line(kind, CFG))
            enqueue.assert_not_called()

    def test_her_cached_voice_even_when_elevenlabs_is_down(self):
        with mock.patch("voice.alerts.player.cached", return_value=True):
            said, offline, enqueue = self.report("quota")
        offline.assert_not_called()
        self.assertEqual(enqueue.call_args.args[1]["text"], alerts.line("quota", CFG))

    def test_no_player_means_system_voice(self):
        with mock.patch("voice.alerts.player.cached", return_value=True):
            said, offline, enqueue = self.report("player")
        offline.assert_called_once()
        enqueue.assert_not_called()

    def test_every_line_names_what_to_check(self):
        for kind, text in alerts.LINES.items():
            if kind not in ("clipboard", "realtime"):
                self.assertRegex(text, r"^(Falla|Falta)", kind)

    def test_not_twice_in_a_row(self):
        self.assertTrue(self.report("mic")[0])
        self.assertFalse(self.report("mic")[0])
        self.assertTrue(self.report("stt")[0])  # another kind is news
        with mock.patch("voice.alerts.time.time", return_value=10**10):
            self.assertTrue(self.report("mic")[0])  # after the cooldown

    def test_clipboard_every_time(self):
        self.assertTrue(self.report("clipboard")[0])
        self.assertTrue(self.report("clipboard")[0])

    def test_quiet_when_muted_or_off(self):
        self.assertFalse(self.report("mic", {**CFG, "muted": True})[0])
        self.assertFalse(self.report("stt", {**CFG, "report_errors": False})[0])

    def test_never_raises(self):
        with mock.patch("voice.alerts.due", side_effect=RuntimeError("boom")), mock.patch("voice.hooks.log"):
            self.assertFalse(alerts.report("mic", CFG))

    def test_worker_crash_is_reported(self):
        with mock.patch("voice.cli.hooks.work", side_effect=TTSError('ElevenLabs 401: quota_exceeded')), \
                mock.patch("voice.cli.alerts.report") as report:
            cli.cmd_worker(mock.Mock(kind="reply", payload="x"), CFG)
        self.assertEqual(report.call_args.args[:2], ("quota", CFG))


class WarmTest(unittest.TestCase):
    def test_warm_synthesizes_only_what_is_missing(self):
        cfg = {**CFG, "voice_id": "warm-test"}
        with mock.patch("voice.player._stream_cmd", return_value=["mpv"]), \
                mock.patch("voice.player.tts.stream", side_effect=lambda text, cfg: [b"MP3", text.encode()]) as tts:
            self.assertEqual(len(alerts.missing(cfg)), len(alerts.LINES))
            self.assertEqual(alerts.warm(cfg), len(alerts.LINES))
            self.assertEqual(alerts.missing(cfg), [])
            self.assertEqual(alerts.warm(cfg), 0)  # nothing twice
        self.assertEqual(tts.call_count, len(alerts.LINES))

    def test_session_start_prepares_them(self):
        from voice import hooks

        with mock.patch("voice.alerts.missing", return_value=["x"]), mock.patch("voice.hooks.player.spawn") as spawn, \
                mock.patch("voice.hooks._enqueue"), mock.patch("voice.hooks.start_listening"):
            hooks.handle("session", {"session_id": "w", "cwd": ""}, CFG)
        self.assertIn(("_prepara",), [c.args for c in spawn.call_args_list])

    def test_failed_summary_is_reported(self):
        from voice import hooks

        with mock.patch("voice.alerts.report") as report, mock.patch("voice.hooks.log"):
            hooks._logged(lambda reply, cfg: "")("respuesta", CFG)
        self.assertEqual(report.call_args.args[0], "summarizer")


if __name__ == "__main__":
    unittest.main()
