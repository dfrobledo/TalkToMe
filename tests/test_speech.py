import json
import tempfile
import unittest
from pathlib import Path

from jarvis import persona, speakable, transcript
from jarvis.config import DEFAULTS
from jarvis.hooks import compose_reply

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
        self.assertIn("He dejado el código en pantalla.", spoken)

    def test_lead_is_first_prose_paragraph(self):
        self.assertEqual(
            speakable.lead(REPLY), "Listo, señor. Las pruebas pasan y el cambio está en la rama."
        )

    def test_lead_skips_leading_heading_and_list(self):
        self.assertEqual(speakable.lead("# Título\n\n- uno\n\nHola, señor."), "Hola, señor.")

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

    def test_long_reply_speaks_lead_plus_pointer(self):
        said = compose_reply(REPLY, self.cfg)
        self.assertTrue(said.startswith("Listo, señor."))
        self.assertTrue(said.endswith("El detalle está en pantalla, señor."))

    def test_short_reply_spoken_in_full(self):
        self.assertEqual(compose_reply("Hecho, **señor**.", self.cfg), "Hecho, señor.")


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
        self.assertEqual(line, "Disculpe, señor. Necesito su autorización para usar Bash.")

    def test_ignores_non_attention_notifications(self):
        self.assertEqual(persona.notification({"notification_type": "auth_success"}, "señor"), "")


if __name__ == "__main__":
    unittest.main()
