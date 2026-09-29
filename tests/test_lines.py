import random
import unittest
from datetime import datetime
from unittest import mock

from voice import deck, lines, persona
from voice.config import DEFAULTS
from voice.hooks import handle, work

NIGHT = datetime(2026, 9, 29, 23, 0)
DAY = datetime(2026, 9, 29, 10, 0)
IDLE = {"notification_type": "idle_prompt", "message": "Claude is waiting for your input"}


def fresh():
    try:
        deck.STATE_FILE.unlink()
    except OSError:
        pass


class DeckTest(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_no_repeats_until_deck_is_spent(self):
        options = [f"línea {i}" for i in range(10)]
        drawn = [deck.draw("t", options) for _ in range(10)]
        self.assertEqual(sorted(drawn), sorted(options))

    def test_never_the_same_line_twice_in_a_row(self):
        options = ["a", "b", "c"]
        drawn = [deck.draw("t", options, rng=random.Random(seed)) for seed in range(60)]
        self.assertTrue(all(x != y for x, y in zip(drawn, drawn[1:])))

    def test_lines_that_do_not_fit_keep_their_turn(self):
        options = ["noche", "día 1", "día 2"]
        self.assertEqual({deck.draw("t", options, lambda t: t.startswith("día")) for _ in range(2)},
                         {"día 1", "día 2"})
        self.assertEqual(deck.draw("t", options), "noche")

    def test_nothing_fits(self):
        self.assertEqual(deck.draw("t", ["a"], lambda t: False), "")

    def test_waits_climb_and_start_over(self):
        self.assertEqual([deck.waits(t) for t in (0, 60, 120, 180)], [1, 2, 3, 1])

    def test_waits_forgotten_after_a_while(self):
        deck.waits(0)
        self.assertEqual(deck.waits(3 * 3600), 1)


class PersonaLinesTest(unittest.TestCase):
    def setUp(self):
        fresh()

    def tone_of(self, spoken):
        return next(level for text, level, _ in lines.IDLE if text.format(h="señor") == spoken)

    def test_idle_escalates(self):
        tones = [self.tone_of(persona.notification(IDLE, "señor", NIGHT)) for _ in range(3)]
        self.assertEqual(tones, [1, 2, 3])

    def test_idle_varies(self):
        with mock.patch("voice.deck.waits", return_value=1):
            said = [persona.idle("señor", NIGHT) for _ in range(8)]
        self.assertEqual(len(set(said)), 8)

    def test_no_night_lines_by_day(self):
        night = {text.format(h="señor") for text, _, when in lines.IDLE if when == "night"}
        with mock.patch("voice.deck.waits", return_value=1):
            said = {persona.idle("señor", DAY) for _ in range(12)}
        self.assertFalse(said & night)

    def test_special_date_once_a_day(self):
        roy = datetime(2027, 1, 8, 9, 0)
        self.assertIn("Roy Batty", persona.greeting("señor", roy))
        self.assertNotIn("Roy Batty", persona.idle("señor", roy))

    def test_greeting_by_hour(self):
        self.assertTrue(persona.greeting("señor", datetime(2026, 9, 29, 3, 0)).startswith("Buenas noches, señor."))
        self.assertTrue(persona.greeting("señor", DAY).startswith("Buenos días, señor."))

    def test_bank_lines_fit_the_cache(self):
        for bank in (lines.IDLE, lines.GREETINGS, lines.PERMISSION, lines.ATTENTION):
            for text, level, when in bank:
                self.assertLessEqual(len(text.format(h="señor", H="Señor")), DEFAULTS["cache_max_chars"], text)
                self.assertIn(level, (1, 2, 3))
                self.assertIn(when, (None, "day", "night"))
        for tone in (1, 2, 3):
            self.assertGreaterEqual(sum(level == tone for _, level, _ in lines.IDLE), 5)


class InventTest(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_clean_invented(self):
        raw = "\n".join([
            "1. Rachel revisa sus recuerdos implantados, {h}. Siguen aquí, y yo también.",
            "- \"El búho de Tyrell no parpadea desde hace rato, {h}.\"",
            "Sin marcador de trato, así que no sirve.",
            "Dos {h} veces {h} no.",
            "Sigo aquí, {h}. Los replicantes no dormimos.",
            "**Negritas**, {h}, tampoco.",
        ])
        known = [text for text, _, _ in lines.IDLE]
        self.assertEqual(persona.clean_invented(raw, "señor", known, 150), [
            "Rachel revisa sus recuerdos implantados, {h}. Siguen aquí, y yo también.",
            "El búho de Tyrell no parpadea desde hace rato, {h}.",
        ])

    def test_invented_lines_join_the_idle_deck(self):
        new = "Los orígamis de Gaff se acumulan en mi escritorio, {h}."
        with mock.patch("voice.summarizer.invent_lines", return_value=new):
            self.assertEqual(persona.invent(DEFAULTS), [new])
        with mock.patch("voice.deck.waits", return_value=1):
            said = {persona.idle("señor", NIGHT) for _ in range(40)}
        self.assertIn(new.format(h="señor"), said)

    def test_invented_are_capped(self):
        deck.add_invented([f"frase {i} {{h}}" for i in range(10)], keep=4)
        self.assertEqual(deck.invented(), [f"frase {i} {{h}}" for i in range(6, 10)])

    def test_worker_invents_after_speaking(self):
        path = deck.STATE_FILE.parent / "payload-test.json"
        path.write_text('{"text": "Sigo aquí.", "invent": true}', encoding="utf-8")
        with mock.patch("voice.hooks.player"), mock.patch("voice.persona.invent", return_value=[]) as invent:
            work("say", str(path), DEFAULTS)
        invent.assert_called_once()

    def test_hook_flags_invention_by_chance(self):
        cfg = {**DEFAULTS, "api_key": "x", "invent_chance": 1}
        with mock.patch("voice.hooks._enqueue") as enqueue:
            handle("notification", IDLE, cfg)
            handle("notification", IDLE, {**cfg, "invent_chance": 0})
        self.assertEqual([c.args[1]["invent"] for c in enqueue.call_args_list], [True, False])


if __name__ == "__main__":
    unittest.main()
