"""Her voice is protected: the accident that lost it, and every other way to lose it, reproduced.

Your config lives outside the repository, every change is backed up, every
voice is remembered, and the voice is mirrored into .env, which every version
of TalkToMe ever released reads.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voice import cli, config, tts
from voice.config import DEFAULTS

HERS = "KUz5UyNoj6LLiCfCyGlM"
OTHER = "qBo1aZGQ5DObYNGJ7AFa"
REPO_CONFIG = Path(__file__).resolve().parent.parent / "talktome.config.json"


class Machine:
    """A PC with TalkToMe cloned: its own repository config and .env, and the user's config dir."""

    def __init__(self, test):
        self.root = Path(tempfile.mkdtemp(prefix="maquina-"))
        test.addCleanup(shutil.rmtree, self.root, True)
        self.repo_config = self.root / "talktome.config.json"
        self.env = self.root / ".env"
        self.user = self.root / "AppData" / "TalkToMe"
        self.clone()
        self.env.write_text("ELEVENLABS_API_KEY=sk_mi_clave_secreta\n", encoding="utf-8")
        patch = mock.patch.dict(os.environ, {"TALKTOME_CONFIG": str(self.repo_config),
                                             "TALKTOME_ENV_FILE": str(self.env), "TALKTOME_USER_DIR": str(self.user)})
        patch.start()
        test.addCleanup(patch.stop)
        for key in ("ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID", "ELEVENLABS_API_KEY"):
            os.environ.pop(key, None)

    def clone(self):
        """The repository's talktome.config.json as git has it: the project's defaults."""
        shutil.copy(REPO_CONFIG, self.repo_config)

    def load(self):
        for key in ("ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID", "ELEVENLABS_API_KEY"):
            os.environ.pop(key, None)
        return config.load()


class AccidentTest(unittest.TestCase):
    def test_reset_hard_no_longer_loses_her_voice(self):
        pc = Machine(self)
        # Before: her voice (and her pace) edited into the repository's config, as the old code did.
        data = json.loads(pc.repo_config.read_text())
        data["voice_id"], data["voice_settings"]["speed"] = HERS, 0.93
        pc.repo_config.write_text(json.dumps(data))
        cfg = pc.load()
        self.assertEqual((cfg["voice_id"], cfg["voice_settings"]["speed"]), (HERS, 0.93))
        # The first load moved them out of the repository.
        moved = json.loads((pc.user / "config.json").read_text())
        self.assertEqual((moved["voice_id"], moved["voice_settings"]), (HERS, {"speed": 0.93}))
        # `git reset --hard`: the repository's config back to the defaults.
        pc.clone()
        cfg = pc.load()
        self.assertEqual((cfg["voice_id"], cfg["voice_settings"]["speed"]), (HERS, 0.93))
        self.assertFalse(cfg["voice_healed"])

    def test_fresh_clone_and_git_clean(self):
        pc = Machine(self)
        pc.load()
        config.save_voice_id(HERS, "Rachel")
        # Delete everything in the repository folder, .env included, and clone again.
        pc.env.unlink()
        pc.clone()
        pc.env.write_text("ELEVENLABS_API_KEY=sk_mi_clave_secreta\n", encoding="utf-8")
        self.assertEqual(pc.load()["voice_id"], HERS)
        self.assertIn(f"ELEVENLABS_VOICE_ID={HERS}", pc.env.read_text())  # the copy comes back by itself

    def test_config_lost_the_history_remembers(self):
        pc = Machine(self)
        pc.load()
        config.save_voice_id(HERS, "Rachel")
        (pc.user / "config.json").unlink()
        cfg = pc.load()
        self.assertEqual((cfg["voice_id"], cfg["voice_healed"]), (HERS, True))

    def test_choosing_the_stand_in_on_purpose_is_respected(self):
        pc = Machine(self)
        pc.load()
        config.save_voice_id(HERS, "Rachel")
        config.save_voice_id(config.STAND_IN, "Lily")
        cfg = pc.load()
        self.assertEqual((cfg["voice_id"], cfg["voice_healed"]), (config.STAND_IN, False))

    def test_every_change_is_backed_up(self):
        pc = Machine(self)
        pc.load()
        for i in range(13):
            config.save_setting("max_chars", 400 + i)
        backups = sorted((pc.user / "respaldos").glob("config-*.json"))
        self.assertEqual(len(backups), config.BACKUPS)
        self.assertEqual(json.loads(backups[-1].read_text())["max_chars"], 411)  # the state before the last change
        self.assertEqual(pc.load()["max_chars"], 412)


class MirrorTest(unittest.TestCase):
    def test_api_key_kept_and_utf16_becomes_utf8(self):
        pc = Machine(self)
        pc.env.write_bytes("ELEVENLABS_API_KEY=sk_mi_clave_secreta\r\n# nota\r\n".encode("utf-16"))
        config.save_voice_id(HERS, "Rachel")
        text = pc.env.read_bytes().decode("utf-8")  # plain UTF-8: every version reads it
        self.assertIn("ELEVENLABS_API_KEY=sk_mi_clave_secreta", text)
        self.assertIn("# nota", text)
        self.assertEqual(text.count("ELEVENLABS_VOICE_ID="), 1)
        self.assertEqual(pc.load()["api_key"], "sk_mi_clave_secreta")
        self.assertFalse(config.sync_mirror(HERS))  # already up to date: .env is not rewritten
        self.assertTrue(list((pc.user / "respaldos").glob(".env-*")))  # .env backed up before its first change

    def test_your_config_wins_over_a_stale_copy(self):
        pc = Machine(self)
        config.save_voice_id(HERS, "Rachel")
        data = json.loads((pc.user / "config.json").read_text())
        data["voice_id"] = OTHER  # edited by hand
        (pc.user / "config.json").write_text(json.dumps(data))
        self.assertEqual(pc.load()["voice_id"], OTHER)
        self.assertIn(f"ELEVENLABS_VOICE_ID={OTHER}", pc.env.read_text())
        self.assertNotIn(HERS, pc.env.read_text())

    def test_a_manual_override_still_works(self):
        pc = Machine(self)
        config.save_voice_id(HERS, "Rachel")
        with mock.patch.dict(os.environ, {"ELEVENLABS_VOICE_ID": OTHER}):
            self.assertEqual(config.load()["voice_id"], OTHER)
        self.assertIn(f"ELEVENLABS_VOICE_ID={HERS}", pc.env.read_text())  # the test voice is not saved


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO_CONFIG.parent, capture_output=True, text=True)


# Versions users may go back to: the first one, Rachel's arrival, phase 1 and phase 2a.
OLD_VERSIONS = {"8ce24f7": "la primera", "3ae400a": "llega Rachel", "deb1f83": "fase 1", "42c092e": "fase 2a"}


class OlderVersionsTest(unittest.TestCase):
    """The real code of earlier versions, taken from git, finds her voice in .env."""

    def test_every_older_version_finds_her_voice(self):
        if _git("rev-parse", "--git-dir").returncode:
            self.skipTest("sin historial de git")
        pc = Machine(self)
        config.save_voice_id(HERS, "Rachel")
        checked = 0
        for commit, name in OLD_VERSIONS.items():
            if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode:
                continue  # a shallow clone without that history
            package = "jarvis" if not _git("cat-file", "-e", f"{commit}:jarvis/config.py").returncode else "voice"
            old = Path(tempfile.mkdtemp(prefix=f"version-{commit}-"))
            self.addCleanup(shutil.rmtree, old, True)
            (old / package).mkdir()
            (old / package / "__init__.py").write_text("")
            (old / package / "config.py").write_text(_git("show", f"{commit}:{package}/config.py").stdout)
            for cfg_file in ("talktome.config.json", "jarvis.config.json"):
                shown = _git("show", f"{commit}:{cfg_file}")
                if not shown.returncode:
                    (old / cfg_file).write_text(shown.stdout)
            shutil.copy(pc.env, old / ".env")
            env = {k: v for k, v in os.environ.items() if not k.startswith(("ELEVENLABS_", "TALKTOME_CONFIG"))}
            env["TALKTOME_STATE"] = str(old / "state")
            out = subprocess.run([sys.executable, "-c", f"from {package} import config; print(config.load()['voice_id'])"],
                                 cwd=old, env=env, capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), HERS, f"versión {commit} ({name}): {out.stderr[-300:]}")
            checked += 1
        if not checked:
            self.skipTest("sin las versiones anteriores en este clon")


class RecoverTest(unittest.TestCase):
    def test_recover_by_the_cache(self):
        pc = Machine(self)
        cfg = pc.load()
        with mock.patch("voice.player._stream_cmd", return_value=["mpv"]):
            for text in cli.cached_lines(cfg)[:5]:
                path = tts.cache_path(text, {**cfg, "voice_id": HERS}, "mp3")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"audio")
            library = [{"voice_id": OTHER, "name": "Rachel"}, {"voice_id": HERS, "name": "Rachel"}]
            with mock.patch("voice.cli.tts.voices", return_value=library), mock.patch("builtins.print"):
                self.assertEqual(cli.cmd_voices(mock.Mock(recuperar=True, usar=None, historial=False), cfg), 0)
        self.assertEqual(pc.load()["voice_id"], HERS)
        self.assertEqual(config.voice_history()[-1]["voice_id"], HERS)

    def test_two_voices_with_her_name_are_played_and_chosen(self):
        pc = Machine(self)
        latino = cli.ACCENTS["latino"]
        library = [{"voice_id": OTHER, "name": "Rachel", "description": "Latin American woman... Spanish speaker"},
                   {"voice_id": HERS, "name": "Rachel", "description": f"... native Spanish speaker with {latino}, ..."}]
        with mock.patch("voice.cli.tts.voices", return_value=library), mock.patch("builtins.print") as out, \
                mock.patch("voice.cli.player.speak") as speak, mock.patch("voice.cli.player.claim"), \
                mock.patch("voice.cli.player.release"), mock.patch("builtins.input", return_value="2"):
            cli.cmd_voices(mock.Mock(usar="Rachel", recuperar=False, historial=False), {**DEFAULTS, "api_key": "k"})
        self.assertEqual([c.args[1]["voice_id"] for c in speak.call_args_list], [OTHER, HERS])
        self.assertEqual(pc.load()["voice_id"], HERS)
        printed = " ".join(str(c.args[0]) for c in out.call_args_list)
        self.assertIn("acento latino", printed)
        self.assertIn("versión antigua", printed)


if __name__ == "__main__":
    unittest.main()
