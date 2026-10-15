"""Draft (16 Oct, 12:45): a time said without am or pm counts as said ("7 to 10pm": the 7 is mine), so the
stated-time check never swaps a range's start for its end. Apply with no self-test running, then delete."""
from pathlib import Path


def patch(path, pairs):
    p = Path(path)
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    t = raw.replace("\r\n", "\n")
    for old, new in pairs:
        assert t.count(old) == 1, (path, old[:70], t.count(old))
        t = t.replace(old, new, 1)
    p.write_bytes((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))


patch("core/actions.py", [
    ('''def _given_minutes(value) -> int | None:''', '''# A time of day with no am or pm ("7" in "7 to 10pm", "7:30"): never in front of am or pm, a % or a word
_BARE_TIME = re.compile(r"(?<![\\w:.$])(\\d{1,2})(?:[:.](\\d{2}))?(?!\\s*[ap]\\.?m\\b)(?![\\w:.%])", re.IGNORECASE)


def _bare_times(said: str) -> set[int]:
    """The times a message gives with no am or pm, as minutes of a twelve-hour clock (7 and 7 pm alike)."""
    return {(int(hour) % 12) * 60 + int(minute or 0) for hour, minute in _BARE_TIME.findall(said) if 1 <= int(hour) <= 12 and int(minute or 0) < 60}


def _given_minutes(value) -> int | None:'''),
    ('''    missing = [each for each in dict.fromkeys(stated) if each not in minutes]
    odd = [value for value, at in zip(given, minutes) if at is not None and at not in stated]''', '''    missing = [each for each in dict.fromkeys(stated) if each not in minutes]
    # A time handed over that I said without am or pm is mine too, never the odd one: in "dinner 7 to 10pm"
    # the start is 7 pm and 10 pm its end (found 16 Oct: the start was swapped for the end, 7 pm -> 10 pm)
    bare = _bare_times(said)
    odd = [value for value, at in zip(given, minutes) if at is not None and at not in stated and at % 720 not in bare]'''),
])

patch("tests/test_actions.py", [
    ('''        ({"pills": [{"name": "A", "notes": "with food"}]}, "9pm"),  # no time handed over at all
    ):''', '''        ({"pills": [{"name": "A", "notes": "with food"}]}, "9pm"),  # no time handed over at all
        ({"pills": [{"name": "A", "times": ["7:00 pm"]}]}, "dinner 7 to 10pm"),  # a range: the 7 is mine, said without pm
        ({"pills": [{"name": "A", "times": ["7:30 pm"]}]}, "7:30 until 9pm"),
    ):'''),
])

p = Path("tests/test_calendar_repeating.py")
t = p.read_bytes().decode("utf-8").replace("\r\n", "\n").rstrip("\n") + '''


def test_a_range_said_with_one_am_or_pm_keeps_its_start(world):
    """Found 16 Oct on live: "… 7 to 10pm" had its start put back to 10 pm by the stated-time check."""
    from core import actions

    add = next(each for each in plain.writing_actions() if each.name == "calendar_add")
    data = {"title": "dinner", "day": "Friday", "time": "7:00 pm", "length": 180}
    assert actions.restated(add, data, "dinner Friday 7 to 10pm") == (data, [])
    assert actions.restated(add, {"title": "dinner", "time": "7:00 pm", "ends_at": "10:00 pm"}, "dinner Friday 7 to 10pm")[1] == []
'''
p.write_bytes((t + "\n").replace("\n", "\r\n").encode("utf-8"))
print("ok")
