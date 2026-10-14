"""The design preview (selftest/preview.py) and the design loop's reading of Alex's replies (docs/DESIGN-LOG.md)."""
import re
from types import SimpleNamespace

from core import design
from selftest import preview


def test_every_message_of_the_preview_fits_one_message_and_names_only_made_up_pills():
    found = preview.checked()
    assert len(found) >= 9
    words = "\n".join(text for _, pieces in found for text in design.texts(pieces))
    assert set(re.findall(r"\*\*(Pill [A-Z])\*\*", words)) <= {f"Pill {letter}" for letter in "ABCDE"}
    names = set(re.findall(r"\*\*([A-Z][a-z]+(?: [A-Z][a-z]*)?)\*\*", words))
    assert names <= {"Pill", "Dose"} | {f"Pill {letter}" for letter in "ABCDE"} | {"Next"}, f"a name that is not made up: {names}"


def test_a_round_s_preview_opens_with_its_title():
    assert preview.opening("Round 4").splitlines()[0] == "## Round 4"
    assert preview.opening().startswith(f"## {preview.TITLE}")


def test_only_what_people_said_after_the_latest_round_is_read_back():
    bot, alex = SimpleNamespace(bot=True), SimpleNamespace(bot=False)
    history = [
        SimpleNamespace(author=bot, content="## Round 3 built"),
        SimpleNamespace(author=alex, content="the dots are too small"),
        SimpleNamespace(author=bot, content="## Round 4"),
        SimpleNamespace(author=bot, content="### The briefing"),
        SimpleNamespace(author=alex, content="better, but the title wraps"),
        SimpleNamespace(author=alex, content="  "),
    ]
    assert [each.content for each in preview.since_last_round(history)] == ["better, but the title wraps"]
    assert [each.content for each in preview.since_last_round(history[:2])] == ["the dots are too small"]
    assert [each.content for each in preview.since_last_round([SimpleNamespace(author=alex, content="hi")])] == ["hi"], "no round yet: everything"
