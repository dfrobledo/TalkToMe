"""Company while Claude works on something said out loud: acks, thinking sounds, progress."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from voice import companion, hooks, lines, persona, player, transcript
from voice.config import DEFAULTS

CFG = {**DEFAULTS, "api_key": "k"}


def tool_use(name, **tool_input):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input}]}}


class Transcript:
    def __init__(self):
        self.path = Path(tempfile.mkdtemp()) / "session.jsonl"
        self.path.write_text(json.dumps({"type": "user", "message": {"content": "hola"}}) + "\n", encoding="utf-8")

    def add(self, entry, newline=True):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + ("\n" if newline else ""))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ActivityTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(persona.activity("Read"), "read")
        self.assertEqual(persona.activity("Grep", {"pattern": "x"}), "read")
        self.assertEqual(persona.activity("Edit"), "edit")
        self.assertEqual(persona.activity("Bash", {"command": "python -m pytest tests/"}), "test")
        self.assertEqual(persona.activity("Bash", {"command": "npm run test"}), "test")
        self.assertEqual(persona.activity("Bash", {"command": "git log --oneline"}), "git")
        self.assertEqual(persona.activity("Bash", {"command": "cd repo && git status"}), "git")
        self.assertEqual(persona.activity("Bash", {"command": "ls -la"}), "shell")
        self.assertEqual(persona.activity("WebSearch"), "web")
        self.assertEqual(persona.activity("Agent"), "agent")
        self.assertEqual(persona.activity("TodoWrite"), "plan")
        self.assertEqual(persona.activity("mcp__github__get_me"), "other")
        self.assertIsNone(persona.activity("ToolSearch"))

    def test_lines_fit_the_cache(self):
        banks = [lines.ACKS, lines.THINKING, lines.THINKING_V3] + list(lines.PROGRESS.values())
        for bank in banks:
            for text, level, when in bank:
                self.assertLessEqual(len(text.format(h="señor", H="Señor")), DEFAULTS["cache_max_chars"], text)
                self.assertIn(level, (1, 2, 3))
                self.assertIn(when, (None, "day", "night"))
        for tone in (1, 2, 3):
            self.assertTrue(any(level == tone for _, level, _ in lines.THINKING))
        for kind in ("read", "edit", "test", "git", "shell", "web", "agent", "plan", "other"):
            self.assertTrue(persona.progress(kind, "señor"))

    def test_tags_only_for_eleven_v3(self):
        noon = datetime(2026, 9, 29, 12, 0)
        plain = {persona.thinking("señor", 1, expressive=False, now=noon) for _ in range(30)}
        self.assertFalse(any("[" in line for line in plain))
        tagged = {persona.thinking("señor", 1, expressive=True, now=noon) for _ in range(30)}
        self.assertTrue(any("[" in line for line in tagged))


class TranscriptTest(unittest.TestCase):
    def test_new_tool_calls_only_whole_lines(self):
        t = Transcript()
        start = transcript.size(t.path)
        t.add(tool_use("Read", file_path="a.py"))
        t.add(tool_use("Bash", command="pytest"), newline=False)  # still being written
        calls, offset = transcript.tool_calls(t.path, start)
        self.assertEqual(calls, [("Read", {"file_path": "a.py"})])
        with open(t.path, "a", encoding="utf-8") as f:
            f.write("\n")
        calls, _ = transcript.tool_calls(t.path, offset)
        self.assertEqual(calls, [("Bash", {"command": "pytest"})])
        self.assertEqual(transcript.tool_calls("/no/such/file", 0), ([], 0))


class CompanionTest(unittest.TestCase):
    def setUp(self):
        self.t = Transcript()
        self.session = f"voz-{id(self)}"
        companion.turn_done(self.session).unlink(missing_ok=True)

    def run_turn(self, seconds, events=(), cfg=CFG):
        """A turn of `seconds`; `events`: (at second, transcript entry)."""
        clock, said = Clock(), []
        pending = sorted(events, key=lambda e: e[0])

        def sleep(step):
            clock.sleep(step)
            while pending and pending[0][0] <= clock.now:
                self.t.add(pending.pop(0)[1])
            if clock.now >= seconds:
                player.session_dir(self.session).mkdir(parents=True, exist_ok=True)
                companion.turn_done(self.session).write_text("x")

        def say(text):
            said.append((round(clock.now), text))
            return True

        with mock.patch("voice.companion.player.busy", return_value=False):
            companion.Companion(cfg, self.session, str(self.t.path), clock=clock, sleep=sleep, say=say).run()
        return said

    def test_quick_turn_says_nothing(self):
        self.assertEqual(self.run_turn(4), [])

    def test_thinking_sounds_space_out(self):
        said = self.run_turn(60)
        times = [at for at, _ in said]
        self.assertEqual(times[0], 5)
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertEqual(gaps, sorted(gaps))  # further apart the longer it goes
        self.assertLessEqual(len(said), 6)
        thinking = {text for text, _, _ in lines.THINKING}
        self.assertTrue(all(text.format(h="señor") in {t.format(h="señor") for t in thinking} for _, text in said))

    def test_says_what_claude_is_doing(self):
        said = self.run_turn(20, [(1, tool_use("Bash", command="python -m unittest"))])
        tests = {text.format(h="señor") for text, _, _ in lines.PROGRESS["test"]}
        self.assertIn(said[0][1], tests)
        # The same kind of work again is not news: a thinking sound instead.
        self.assertNotIn(said[1][1], tests)

    def test_turn_done_stops_it(self):
        companion.turn_done(self.session).parent.mkdir(parents=True, exist_ok=True)
        companion.turn_done(self.session).write_text("x")
        with mock.patch("voice.companion.player.claim") as claim:
            companion.accompany(CFG, self.session, str(self.t.path))
        claim.assert_not_called()  # a finished turn's reply must not be cut


class VoiceTurnTest(unittest.TestCase):
    def prompt(self, text, cfg=CFG):
        payload = {"prompt": text, "session_id": "s-voz", "transcript_path": "/tmp/t.jsonl", "cwd": ""}
        with mock.patch("voice.hooks.player.stop"), mock.patch("voice.hooks.player.spawn") as spawn:
            hooks.handle("prompt", payload, cfg)
        return [c.args for c in spawn.call_args_list]

    def test_dictated_prompt_gets_company(self):
        hooks.mark_dictated("Corre las pruebas, por favor.")
        self.assertEqual(self.prompt("Corre las pruebas, por favor."), [("_acompana", "s-voz", "/tmp/t.jsonl")])
        self.assertEqual(self.prompt("Corre las pruebas, por favor."), [])  # the mark is used once

    def test_typed_prompt_does_not(self):
        self.assertEqual(self.prompt("Corre las pruebas"), [])
        hooks.mark_dictated("otra cosa")
        self.assertEqual(self.prompt("Corre las pruebas"), [])

    def test_modes(self):
        self.assertEqual(self.prompt("x", {**CFG, "narrate_progress": "always"}), [("_acompana", "s-voz", "/tmp/t.jsonl")])
        hooks.mark_dictated("x")
        self.assertEqual(self.prompt("x", {**CFG, "narrate_progress": "off"}), [])
        hooks.mark_dictated("x")
        self.assertEqual(self.prompt("x", {**CFG, "muted": True}), [])

    def test_stop_marks_the_turn_done(self):
        companion.turn_done("s-voz").unlink(missing_ok=True)
        with mock.patch("voice.hooks._enqueue") as enqueue:
            hooks.handle("stop", {"session_id": "s-voz", "cwd": ""}, CFG)
        self.assertTrue(companion.turn_done("s-voz").exists())
        self.assertIn("stop_at", enqueue.call_args.args[1])

    def test_timing_line(self):
        folder = player.session_dir("s-t")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "prompt-at").write_text("100.0")
        self.assertEqual(hooks._timing("s-t", 112.5, 113.4), "tiempos: Claude 12.5 s · voz 0.9 s después")
        self.assertEqual(hooks._timing("s-none", None, None), "tiempos: sin datos")


if __name__ == "__main__":
    unittest.main()
