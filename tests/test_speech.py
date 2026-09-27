import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from voice import persona, speakable, transcript
from voice.config import DEFAULTS
from voice.hooks import compose_reply, handle, is_repeat, work

ROCK = (Path(__file__).parent / "rockavionics_reply.md").read_text(encoding="utf-8")
# Opens with plain prose, but that prose misses the question it ends with.
ROCK2 = (Path(__file__).parent / "rockavionics_reply2.md").read_text(encoding="utf-8")

REPLY = """Listo, señor. Las pruebas pasan y el cambio está en la rama.

## Cambios
- Arreglé `src/utils/date_parser.py` para **zonas horarias**.
- Ver [el PR](https://github.com/x/y/pull/1) 🚀

```python
print("hola")
```

| a | b |
|---|---|
"""


class SpeakableTest(unittest.TestCase):
    def test_strips_markdown_code_and_links(self):
        spoken = speakable.to_speech(REPLY)
        for noise in ("`", "**", "##", "|", "print(", "https", "🚀", "src/"):
            self.assertNotIn(noise, spoken)
        self.assertIn("date parser.py", spoken)
        self.assertIn("Ver el PR.", spoken)
        self.assertIn("Le dejé el código en pantalla.", spoken)

    def test_summary_is_first_prose_paragraph(self):
        self.assertEqual(
            speakable.spoken_summary(REPLY), "Listo, señor. Las pruebas pasan y el cambio está en la rama."
        )

    def test_no_summary_when_reply_opens_with_structure(self):
        for reply in ("# Título\n\nHola, señor.", "Encontré esto:\n\n- uno", "Contexto\n- uno\n- dos"):
            self.assertEqual(speakable.spoken_summary(reply), "", reply)
        self.assertEqual(speakable.spoken_summary(ROCK), "")

    def test_needs_input(self):
        self.assertTrue(speakable.needs_input(ROCK))
        self.assertFalse(speakable.needs_input("Listo, señor. Todo en verde."))

    def test_audio_tags_only_kept_for_v3(self):
        self.assertEqual(speakable.to_speech("[sighs] Otra vez, señor."), "Otra vez, señor.")
        self.assertEqual(
            speakable.to_speech("[sighs] Otra vez.", keep_tags=True), "[sighs] Otra vez."
        )

    def test_truncate_at_sentence(self):
        text, cut = speakable.truncate("Primera frase completa. Segunda frase que sobra.", 30)
        self.assertEqual((text, cut), ("Primera frase completa.", True))


class ComposeTest(unittest.TestCase):
    cfg = {**DEFAULTS, "max_chars": 120}

    def test_missing_summary_is_generated(self):
        calls = []

        def fake(reply, cfg):
            calls.append(reply)
            return "Señor, necesito saber si el Pi ya enciende. Meshtastic queda descartado."

        said = compose_reply(ROCK, DEFAULTS, summarize=fake)
        self.assertEqual(calls, [ROCK])
        self.assertTrue(said.startswith("Señor, necesito saber si el Pi ya enciende."))

    def test_existing_summary_skips_summarizer(self):
        said = compose_reply(REPLY, self.cfg, summarize=lambda *a: self.fail("no debía resumir"))
        self.assertTrue(said.startswith("Listo, señor."))

    def test_summarizer_failure_still_flags_the_question(self):
        said = compose_reply(ROCK, DEFAULTS, summarize=lambda *a: "")
        self.assertEqual(said, "Señor, necesito que me responda algo. Está en pantalla.")

    def test_opening_without_the_question_is_not_a_summary(self):
        calls = []
        said = compose_reply(ROCK2, DEFAULTS, summarize=lambda r, c: calls.append(r) or "Señor, ¿ya tiene el Pi 3?")
        self.assertEqual(calls, [ROCK2])
        self.assertTrue(said.startswith("Señor, ¿ya tiene el Pi 3?"))

    def test_opening_plus_heads_up_when_summarizer_fails(self):
        said = compose_reply(ROCK2, DEFAULTS, summarize=lambda *a: "")
        self.assertTrue(said.startswith("Sí. LoRa sigue en brainstorm"))
        self.assertTrue(said.endswith("Señor, necesito que me responda algo. Está en pantalla."))

    def test_summary_that_asks_is_kept(self):
        reply = "Señor, ¿ya tiene el Pi 3? Mientras tanto reviso la norma.\n\n- detalle\n" + "x " * 300
        said = compose_reply(reply, DEFAULTS, summarize=lambda *a: self.fail("no debía resumir"))
        self.assertTrue(said.startswith("Señor, ¿ya tiene el Pi 3?"))

    def test_long_reply_speaks_lead_plus_pointer(self):
        said = compose_reply(REPLY, self.cfg)
        self.assertTrue(said.startswith("Listo, señor."))
        self.assertTrue(said.endswith("El detalle está en pantalla, señor."))

    def test_summary_gets_its_own_limit(self):
        summary = "Revisé todo, señor. " + "Encontré algo importante. " * 20
        cfg = {**self.cfg, "summary_max_chars": 300}
        said = compose_reply(summary + "\n\n- detalle\n" + "x " * 200, cfg)
        spoken = said.removesuffix(" El detalle está en pantalla, señor.")
        self.assertGreater(len(spoken), self.cfg["max_chars"])
        self.assertLessEqual(len(spoken), 300)

    def test_short_reply_spoken_in_full(self):
        self.assertEqual(compose_reply("Hecho, **señor**.", self.cfg), "Hecho, señor.")


class RepeatTest(unittest.TestCase):
    def test_repeat_phrases(self):
        for prompt in ("repite", "Repítelo, Rachel", "rachel, ¿qué dijiste?", "Otra vez por favor", "REPITE."):
            self.assertTrue(is_repeat(prompt), prompt)
        for prompt in ("repite el test con más datos", "no repitas código", "", "¿qué dijiste en el commit?"):
            self.assertFalse(is_repeat(prompt), prompt)

    def test_repeat_blocks_prompt_and_replays(self):
        with mock.patch("voice.hooks.player") as player:
            decision = handle("prompt", {"prompt": "repite"}, DEFAULTS)
        self.assertEqual(decision["decision"], "block")
        player.spawn.assert_called_once_with("_repeat")

    def test_normal_prompt_only_interrupts(self):
        with mock.patch("voice.hooks.player") as player:
            self.assertIsNone(handle("prompt", {"prompt": "arregla el bug"}, DEFAULTS))
        player.stop.assert_called_once()
        player.spawn.assert_not_called()


class TurnTakingTest(unittest.TestCase):
    def run_work(self, payload, busy):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(payload, f)
        f.close()
        with mock.patch("voice.hooks.player") as player:
            player.busy.return_value = busy
            player.wait_turn.return_value = True
            work("say", f.name, DEFAULTS)
        return player

    def test_idle_reminder_dropped_while_speaking(self):
        player = self.run_work({"text": "Sigo aquí.", "polite": True, "skip_if_busy": True}, busy=True)
        player.speak.assert_not_called()
        player.claim.assert_not_called()

    def test_permission_waits_its_turn(self):
        player = self.run_work({"text": "Necesito permiso.", "polite": True}, busy=True)
        player.wait_turn.assert_called_once()
        player.speak.assert_called_once()

    def test_idle_reminder_spoken_when_quiet(self):
        player = self.run_work({"text": "Sigo aquí.", "polite": True, "skip_if_busy": True}, busy=False)
        player.speak.assert_called_once()


class TranscriptTest(unittest.TestCase):
    def write(self, entries):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        f.write("\n".join(json.dumps(e) for e in entries))
        f.close()
        self.addCleanup(Path(f.name).unlink)
        return f.name

    def test_only_text_after_last_tool_call(self):
        path = self.write([
            {"type": "user", "message": {"content": "arregla el bug"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Voy a mirar."},
                {"type": "tool_use", "id": "1", "name": "Read", "input": {}},
            ]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "1"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Arreglado, señor."}]}},
            {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "x"}]}},
        ])
        self.assertEqual(transcript.final_reply(path), "Arreglado, señor.")

    def test_missing_file(self):
        self.assertEqual(transcript.final_reply("/no/existe.jsonl"), "")


class PersonaTest(unittest.TestCase):
    def test_permission_names_tool(self):
        line = persona.notification(
            {"notification_type": "permission_prompt", "message": "Claude needs your permission to use Bash"},
            "señor",
        )
        self.assertTrue(line.startswith("Señor, necesito su permiso para usar Bash."))

    def test_ignores_non_attention_notifications(self):
        self.assertEqual(persona.notification({"notification_type": "auth_success"}, "señor"), "")


if __name__ == "__main__":
    unittest.main()
