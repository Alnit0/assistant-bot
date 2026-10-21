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


def test_the_design_forum_has_one_post_a_round_each_drawn_in_its_round():
    for number in design.ROUNDS:
        found = preview.round_cards(number)
        assert found and preview.round_title(number) == f"Round {number}"
        assert preview.round_opening(number, "Preview").startswith(f"## Round {number} · Preview")
    four = preview.round_cards(4)
    todos = next(pieces for label, pieces in four if label.startswith("To-dos"))
    assert len(design.menus(todos)) == 1, "round 4's to-dos card: one Done dropdown"
    three = preview.round_cards(3)
    assert design.menus(next(pieces for label, pieces in three if label.startswith("To-dos"))) == [], "round 3's: a Done button each"


def test_the_tags_live_preview_and_retired_are_added_only_where_missing():
    assert [name for name, _ in preview.TAGS] == ["Live", "Preview", "Retired"]
    assert [emoji for _, emoji in preview.TAGS] == ["🟢", "🟡", "⚪"]
    assert preview.missing_tags(["Open", "live"]) == [("Preview", "🟡"), ("Retired", "⚪")]
    assert preview.tag_named("preview") == "Preview"


def test_a_posts_tag_is_read_from_its_ids():
    by_id = {1: "Live", 2: "Preview", 3: "Retired", 4: "Open"}
    assert preview.tag_of([1], by_id) == "Live" and preview.tag_of([4, 3], by_id) == "Retired"
    assert preview.tag_of([], by_id) == "Preview" and preview.tag_of(None, by_id) == "Preview"


def test_shipping_a_round_makes_it_live_and_retires_the_one_that_was():
    assert preview.shipped({1: "Retired", 3: "Live", 4: "Preview"}, 4) == {1: "Retired", 3: "Retired", 4: "Live"}
    assert preview.shipped({3: "Live", 4: "Live"}, 4) == {3: "Retired", 4: "Live"}
    assert preview.shipped({3: "Live"}, 3) == {3: "Live"}, "shipping what is live changes nothing"


def test_the_routines_preview_shows_layout_a_layout_b_and_the_today_card_by_the_list_rule():
    found = preview.routines_layout()
    labels = [label for label, _ in found]
    assert any(label.startswith("Layout A") for label in labels) and any(label.startswith("Layout B") for label in labels)
    assert sum("Today card" in label for label in labels) >= 3
    first_a = found[0][1]
    assert len(design.menus(first_a)) == 1 and design.buttons(first_a) == [], "7:10 am: a dropdown for Morning only (Evening is still to come), no buttons"
    evening_b = next(pieces for label, pieces in found if label.startswith("Layout B · Evening"))
    lines = [line for text in design.texts(evening_b) for line in text.splitlines()]
    assert "-# +5 more" in lines and "-# ✅ 4 done" in lines, "12 items, 4 done: three in full and +5 more"
    (menu,) = design.menus(evening_b)
    assert len(menu.options) == 8
    done = found[-1][1]
    assert [text for text in design.texts(done)] == ["-# 🗓️ Today · all done ✅ 6"], "2 routines and 4 to-dos; the reminders are notes"
    assert "A or B?" in preview.routines_opening()


def test_the_routines_reply_labels_each_card_a_or_b_with_its_length_on_a_phone():
    found = preview.routines_compare()
    labels = [label for label, _ in found if label]
    assert labels and all(label.startswith(("A · ", "B · ")) for label in labels)
    assert {label.split(" · ")[1] for label in labels} == {"7:10 am", "8:30 pm, part done", "all done"}
    notes = [design.texts(pieces)[0] for label, pieces in found if not label]
    assert len(notes) == len(labels) and all(note.startswith("-# on a phone: ") for note in notes)
    today_b = next(pieces for label, pieces in found if label.startswith("B · 8:30 pm") and "Today" in label)
    words = "\n".join(design.texts(today_b))
    assert "📝" in words and "🔁" in words, "a mix of to-dos and routines"
    assert preview.phone_note((design.Text("a\nb"),)) == "-# on a phone: 2 lines and 0 controls, under half a screen"
    assert preview.phone_note((design.Text("a"),)) == "-# on a phone: 1 line and 0 controls, under half a screen"
    assert preview.phone_note((design.Text("\n".join("x" * 13)),)) == "-# on a phone: 13 lines and 0 controls, about half a screen"


def test_the_round_4_preview_fits_shows_round_3_beside_it_and_names_only_made_up_pills():
    found = preview.checked(preview.round_4())
    labels = [label for label, _ in found if label]
    assert any("round 3" in label for label in labels) and any("round 4" in label for label in labels)
    assert not any(label.startswith("Variant") for label in labels), "question 67 is answered: one Taken, at once"
    words = "\n".join(text for _, pieces in found for text in design.texts(pieces))
    assert set(re.findall(r"Pill [A-Z]\b", words)) <= {f"Pill {letter}" for letter in "ABCDEF"}
    assert "one Taken that logs at once" in preview.round_4_opening()
    todos = next(pieces for label, pieces in found if label.startswith("To-dos") and label.endswith("round 4"))
    assert len(design.menus(todos)) == 1 and design.buttons(todos) == [], "to-dos: one Done dropdown"
