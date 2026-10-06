import unittest

from skills.timers.durations import (
    DurationError,
    format_duration,
    parse_duration,
    split_duration,
)

MINUTE, HOUR = 60, 3600


class ParseDurationTest(unittest.TestCase):
    def test_seconds(self):
        for text in ("90s", "90 s", "90sec", "90 secs", "90 seconds", "90S"):
            self.assertEqual(parse_duration(text), 90, text)

    def test_minutes(self):
        for text in ("25m", "25 m", "25min", "25 mins", "25 minutes", "25 Minutes"):
            self.assertEqual(parse_duration(text), 25 * MINUTE, text)
        self.assertEqual(parse_duration("1 minute"), MINUTE)

    def test_hours(self):
        for text in ("2h", "2 h", "2hr", "2 hrs", "2 hours", "2 HOURS"):
            self.assertEqual(parse_duration(text), 2 * HOUR, text)
        self.assertEqual(parse_duration("1 hour"), HOUR)

    def test_a_bare_number_is_minutes(self):
        self.assertEqual(parse_duration("25"), 25 * MINUTE)
        self.assertEqual(parse_duration(" 5 "), 5 * MINUTE)

    def test_combined(self):
        for text in ("1h30m", "1h 30m", "1 hour 30 minutes", "1hr30min", "1h30"):
            self.assertEqual(parse_duration(text), 90 * MINUTE, text)
        self.assertEqual(parse_duration("1h 30m 15s"), HOUR + 30 * MINUTE + 15)
        self.assertEqual(parse_duration("2m30s"), 150)
        self.assertEqual(parse_duration("1m30"), 90, "a number straight after minutes is seconds")
        self.assertEqual(parse_duration("1h5"), HOUR + 5 * MINUTE)
        self.assertEqual(parse_duration("1h30m15"), HOUR + 30 * MINUTE + 15)

    def test_decimals(self):
        self.assertEqual(parse_duration("1.5h"), 90 * MINUTE)
        self.assertEqual(parse_duration("0.5 hours"), 30 * MINUTE)
        self.assertEqual(parse_duration("2.5m"), 150)

    def test_clock_style(self):
        self.assertEqual(parse_duration("1:30"), 90 * MINUTE)
        self.assertEqual(parse_duration("0:45"), 45 * MINUTE)
        self.assertEqual(parse_duration("1:30:15"), HOUR + 30 * MINUTE + 15)
        self.assertEqual(parse_duration("0:00:30"), 30)

    def test_not_a_duration(self):
        for text in ("", "   ", "laundry", "m", "25x", "h30", "1h laundry", "25m!", "-5m", "1:75", "1:5",
                     "1.5", "5m 3", "30m 1h", "1h 2h", "5m5m", "1 2", "1h 30 15", "abc123", "1h30.5"):
            with self.assertRaises(DurationError, msg=text):
                parse_duration(text)

    def test_limits(self):
        self.assertEqual(parse_duration("5s"), 5)
        self.assertEqual(parse_duration("24h"), 24 * HOUR)
        with self.assertRaisesRegex(DurationError, "shortest timer is 5 seconds"):
            parse_duration("4s")
        with self.assertRaisesRegex(DurationError, "shortest"):
            parse_duration("0m")
        with self.assertRaisesRegex(DurationError, "longest timer is 24 hours"):
            parse_duration("25h")
        with self.assertRaisesRegex(DurationError, "longest"):
            parse_duration("1441")


class SplitDurationTest(unittest.TestCase):
    def split(self, text):
        return split_duration(text.split())

    def test_duration_only(self):
        self.assertEqual(self.split("25m"), (25 * MINUTE, ""))
        self.assertEqual(self.split("2 hours"), (2 * HOUR, ""))
        self.assertEqual(self.split("1h 30m"), (90 * MINUTE, ""))

    def test_duration_then_label(self):
        self.assertEqual(self.split("1h30 laundry"), (90 * MINUTE, "laundry"))
        self.assertEqual(self.split("25m deep work"), (25 * MINUTE, "deep work"))
        self.assertEqual(self.split("2 hours roast chicken"), (2 * HOUR, "roast chicken"))
        self.assertEqual(self.split("1 hour 30 minutes bread"), (90 * MINUTE, "bread"))
        self.assertEqual(self.split("10 eggs"), (10 * MINUTE, "eggs"))
        self.assertEqual(self.split("90s Tea"), (90, "Tea"), "the label keeps its capitals")

    def test_a_label_that_starts_with_a_number_is_not_swallowed(self):
        self.assertEqual(self.split("5m 3 eggs"), (5 * MINUTE, "3 eggs"))
        self.assertEqual(self.split("1h 2 loads of washing"), (HOUR, "2 loads of washing"))

    def test_a_label_that_starts_with_a_unit_word_is_read_as_the_unit(self):
        # Documented quirk: "10 min walk" is ten minutes labelled "walk"
        self.assertEqual(self.split("10 min walk"), (10 * MINUTE, "walk"))

    def test_no_duration(self):
        for text in ("", "laundry", "laundry 25m", "soon"):
            with self.assertRaises(DurationError, msg=text):
                self.split(text)

    def test_out_of_range_is_reported_as_such(self):
        with self.assertRaisesRegex(DurationError, "longest"):
            self.split("30h laundry")
        with self.assertRaisesRegex(DurationError, "shortest"):
            self.split("2s")


class FormatDurationTest(unittest.TestCase):
    def test_formats(self):
        cases = {45: "45s", 60: "1m", 90: "1m 30s", 1500: "25m", 3600: "1h", 5400: "1h 30m",
                 5415: "1h 30m", 86400: "24h", 0: "0s", 59.6: "1m", -5: "0s"}
        for seconds, expected in cases.items():
            self.assertEqual(format_duration(seconds), expected, seconds)

    def test_round_trip(self):
        for text in ("45s", "25m", "1h 30m", "1m 30s", "2h"):
            self.assertEqual(format_duration(parse_duration(text)), text)


if __name__ == "__main__":
    unittest.main()
