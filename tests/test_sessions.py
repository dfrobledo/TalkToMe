"""Two terminals, two projects: Rachel keeps them apart and says where she speaks from."""
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from voice import deck, lines, persona, player, projects
from voice.config import DEFAULTS
from voice.hooks import _callsign, handle

NIGHT = datetime(2026, 9, 29, 23, 0)


def sleeper(test):
    """A live process standing in for the other terminal's voice."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    test.addCleanup(lambda: (proc.kill(), proc.wait()))
    return proc


def forget():
    for path in (player.PID_FILE, player.LAST_VOICE, player.LAST_SESSION, deck.STATE_FILE):
        path.unlink(missing_ok=True)


class ProjectTest(unittest.TestCase):
    def test_spoken_names(self):
        self.assertEqual(projects.speakable_name("RockAvionics"), "Rock Avionics")
        self.assertEqual(projects.speakable_name("TalkToMe"), "Talk To Me")
        self.assertEqual(projects.speakable_name("rocket_yeah-v2"), "rocket yeah v2")
        self.assertEqual(projects.speakable_name("PCBDesign"), "PCB Design")

    def test_named_after_the_repository_not_the_subfolder(self):
        repo = Path(tempfile.mkdtemp()) / "RockAvionics"
        (repo / ".git").mkdir(parents=True)
        (repo / "firmware" / "src").mkdir(parents=True)
        self.assertEqual(projects.identify(repo / "firmware" / "src", DEFAULTS)[0], "Rock Avionics")

    def test_config_names_and_overrides(self):
        cfg = {**DEFAULTS, "projects": {
            "rockavionics": "la Torre Tyrell",
            "RocketYeah": {"name": "Rocket Yeah", "voice_id": "pris", "voice_settings": {"speed": 1.05}},
        }}
        self.assertEqual(projects.identify("/x/RockAvionics", cfg), ("la Torre Tyrell", cfg))
        name, own = projects.identify("/x/RocketYeah", cfg)
        self.assertEqual((name, own["voice_id"], own["voice_settings"]["speed"]), ("Rocket Yeah", "pris", 1.05))
        self.assertEqual(own["voice_settings"]["stability"], DEFAULTS["voice_settings"]["stability"])
        self.assertEqual(projects.identify("", cfg), ("", cfg))


class IsolationTest(unittest.TestCase):
    def setUp(self):
        forget()

    def say(self, session, text):
        with mock.patch("voice.player._stream_cmd", return_value=None), \
                mock.patch("voice.player.tts.wav", return_value=b"RIFF" + text.encode()), \
                mock.patch("voice.player._play_wav"):
            self.assertTrue(player.speak(text, DEFAULTS, keep=True, session=session))

    def test_each_session_keeps_its_own_reply(self):
        player.keep_markdown("rock", "# Rock")
        self.say("rock", "Los servos responden.")
        player.keep_markdown("rocket", "# Rocket")
        self.say("rocket", "El motor pasó la prueba.")
        self.assertEqual(player.last_spoken("rock"), "Los servos responden.")
        self.assertEqual(player.last_markdown("rock"), "# Rock")
        self.assertEqual(player.last_spoken("rocket"), "El motor pasó la prueba.")
        # From a plain console: the last one said, wherever it came from.
        self.assertEqual(player.last_spoken(), "El motor pasó la prueba.")

    def test_repeat_replays_the_sessions_own_audio(self):
        self.say("rock", "Los servos responden.")
        self.say("rocket", "El motor pasó la prueba.")
        with mock.patch("voice.player._stream_cmd", return_value=None), \
                mock.patch("voice.player._play_wav") as play, mock.patch("voice.player.tts.wav") as wav:
            self.assertTrue(player.replay(DEFAULTS, "rock"))
        play.assert_called_once_with(b"RIFFLos servos responden.")
        wav.assert_not_called()

    def test_typing_in_one_terminal_only_silences_that_one(self):
        other = sleeper(self)
        player.PID_FILE.write_text(str(other.pid))  # the other terminal is speaking
        worker = player.session_dir("rock") / "worker.pid"
        worker.parent.mkdir(parents=True, exist_ok=True)
        worker.write_text("424242")
        with mock.patch("voice.player._kill", return_value=True) as kill:
            handle("prompt", {"prompt": "arregla el bug", "session_id": "rock"}, DEFAULTS)
        kill.assert_called_once_with(424242)
        self.assertEqual(player._pid(player.PID_FILE), other.pid)

    def test_another_session_is_not_cut_off(self):
        other = sleeper(self)
        player.PID_FILE.write_text(str(other.pid))
        with mock.patch("voice.player._say") as say:
            self.assertFalse(player.speak("Hola.", DEFAULTS, session="rock", wait=0))
        say.assert_not_called()
        self.assertEqual(player._pid(player.PID_FILE), other.pid)

    def test_floor_left_by_a_dead_speaker_is_taken(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        player.PID_FILE.write_text(str(dead.pid))
        with mock.patch("voice.player._say") as say:
            self.assertTrue(player.speak("Hola.", DEFAULTS, session="rock", wait=0))
        say.assert_called_once()
        self.assertFalse(player.PID_FILE.exists())  # given back after speaking


class CallsignTest(unittest.TestCase):
    def setUp(self):
        forget()

    def spoken(self, session, project, cfg=DEFAULTS):
        player.remember_project(session, project)
        said = []
        with mock.patch("voice.player._say", side_effect=lambda text, *a, **k: said.append(text)):
            player.speak("Listo, señor.", cfg, session=session, intro=_callsign(project, cfg))
        return said

    def test_named_only_when_the_voice_changes_project(self):
        self.assertEqual(self.spoken("rock", "Rock Avionics"), ["Listo, señor."])
        self.assertEqual(self.spoken("rock", "Rock Avionics"), ["Listo, señor."])
        switch = self.spoken("rocket", "Rocket Yeah")
        self.assertEqual(len(switch), 2)
        self.assertIn("Rocket Yeah", switch[0])
        back = self.spoken("rock", "Rock Avionics")
        self.assertIn("Rock Avionics", back[0])

    def test_always_and_off(self):
        self.spoken("rock", "Rock Avionics")
        always = self.spoken("rock", "Rock Avionics", {**DEFAULTS, "announce_project": "always"})
        self.assertIn("Rock Avionics", always[0])
        off = self.spoken("rocket", "Rocket Yeah", {**DEFAULTS, "announce_project": "off"})
        self.assertEqual(off, ["Listo, señor."])

    def test_callsigns_vary_and_fit_the_cache(self):
        said = {persona.callsign("Rock Avionics", "señor", NIGHT) for _ in range(8)}
        self.assertEqual(len(said), 8)
        for bank in (lines.CALLSIGNS, lines.SESSION_OPENINGS):
            for text, _, when in bank:
                self.assertIn("{p}", text)
                self.assertIn(when, (None, "day", "night"))
                spoken = text.format(h="señor", H="Señor", p="Rock Avionics")
                self.assertLessEqual(len(spoken), 60, text)

    def test_greeting_names_the_project(self):
        greeting = persona.greeting("señor", NIGHT, project="Rock Avionics")
        self.assertTrue(greeting.startswith("Buenas noches, señor."))
        self.assertIn("Rock Avionics", greeting)

    def test_session_start_greets_with_project(self):
        cfg = {**DEFAULTS, "api_key": "x"}
        with mock.patch("voice.hooks._enqueue") as enqueue:
            handle("session", {"session_id": "rock", "cwd": "/x/RockAvionics", "source": "startup"}, cfg)
        payload = enqueue.call_args.args[1]
        self.assertIn("Rock Avionics", payload["text"])
        self.assertEqual((payload["session_id"], payload["callsign"]), ("rock", False))


if __name__ == "__main__":
    unittest.main()
