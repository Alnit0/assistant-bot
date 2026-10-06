import unittest

from core.router import Router


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.router = Router()
        self.router.add("stats", "stats")
        self.router.add("reset", "reset", exact=True)
        self.router.add("timer", "timer", takes_args=True)
        self.router.add("timers", "timers")
        self.router.add("lab chart", "chart", takes_args=True)
        self.router.add("extend", "extend", takes_args=True)
        self.router.add_pattern(r"\+\s*(.+)", "extend")

    def match(self, text):
        found = self.router.match(text)
        return None if found is None else (found.entry, found.args, found.corrected)

    def test_whole_message_must_be_the_word(self):
        self.assertEqual(self.match("stats"), ("stats", [], False))
        self.assertEqual(self.match("  STATS! "), ("stats", [], False))
        self.assertIsNone(self.match("stats please"))
        self.assertIsNone(self.match("my stats"))

    def test_arguments_keep_their_capitals(self):
        self.assertEqual(self.match("Timer 5m Roast Chicken"), ("timer", ["5m", "Roast", "Chicken"], False))
        self.assertEqual(self.match("LAB CHART Matplotlib 30"), ("chart", ["Matplotlib", "30"], False))

    def test_the_longest_phrase_wins(self):
        self.assertEqual(self.match("timers"), ("timers", [], False))
        self.assertEqual(self.match("timer"), ("timer", [], False))

    def test_one_letter_typos_in_longer_words(self):
        self.assertEqual(self.match("statss"), ("stats", [], True))
        self.assertEqual(self.match("lab chrat 7"), ("chart", ["7"], True))
        self.assertIsNone(self.match("stat"), "four letters: too short to guess at")
        self.assertIsNone(self.match("resett"), "exact entries never match by typo")

    def test_a_typo_that_could_be_two_things_matches_neither(self):
        self.assertIsNone(self.match("timerz"), "timer or timers?")

    def test_patterns(self):
        self.assertEqual(self.match("+10m"), ("extend", ["10m"], False))
        self.assertEqual(self.match("+ 10 min"), ("extend", ["10", "min"], False))
        self.assertEqual(self.match("extend 5m"), ("extend", ["5m"], False))
        self.assertIsNone(self.match("+"))
        self.assertIsNone(self.match("10m"))

    def test_duplicate_phrases_are_refused(self):
        with self.assertRaises(ValueError):
            self.router.add("stats", "again")


if __name__ == "__main__":
    unittest.main()
