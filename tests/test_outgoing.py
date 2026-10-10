"""The last check on what the bot sends (core/outgoing.py): nothing internal, and no offers."""
import pytest

from core import actions, outgoing
from tasks import registry


@pytest.fixture(autouse=True)
def names():
    registry.load()  # sets the action names that must never be shown
    yield


@pytest.mark.parametrize(
    "text, found",
    [
        ("(nothing)", ["(nothing)"]),
        ("Saved. (nothing)", ["(nothing)"]),
        ("I ran pill_add for you", ["pill_add"]),
        ("timer_change: paused tea", ["timer_change"]),
        ("the item is @that", ["@that"]),
        ("[[about-my-data]]", ["[[about-my-data]]"]),
        ("✅ Saved · 💊 **Iron** · daily at `8:00 pm`", []),
        ("⏸️ Paused: tea (9m 21s left)", []),
        ("nothing to remove", []),
        ("none of them is running", []),
    ],
)
def test_internal_labels_are_found_and_ordinary_words_are_not(text, found):
    assert outgoing.leaks(text) == found


def test_every_action_name_of_every_task_is_one_of_them():
    for entry in actions.catalogue():
        for action in entry.actions:
            assert outgoing.leaks(f"done: {action.name}") == [action.name]


def test_a_label_is_taken_out_and_what_is_left_is_sent(monkeypatch):
    logged = []
    monkeypatch.setattr(outgoing.log, "error", lambda text, *args: logged.append(text % args))
    assert outgoing.clean("✅ Saved · pill_add · **Iron**") == "✅ Saved · · **Iron**"
    assert outgoing.clean("(nothing)") == "", "nothing left: nothing is sent"
    assert outgoing.clean("Timers\n(nothing)\ntea · 5m") == "Timers\ntea · 5m"
    assert outgoing.clean("✅ Saved · 💊 **Iron**") == "✅ Saved · 💊 **Iron**"
    assert len(logged) == 3 and logged[0].startswith("An internal label was about to be sent to the user: pill_add")


@pytest.mark.parametrize(
    "said, kept",
    [
        ("You've got milk on your shopping list. Want to add anything else or tick something off?", "You've got milk on your shopping list."),
        ("Paris. Want me to tell you more?", "Paris."),
        ("It's about 3 km. Would you like me to work out the walking time?", "It's about 3 km."),
        ("Paris.\n\nAnything else?", "Paris."),
        ("Sure. Let me know if you need anything else!", "Sure."),
        ("I hear you! Anything I can help make it quicker?", "I hear you!"),
        ("Paris is the capital. Shall I list the others?", "Paris is the capital."),
        ("Is it Paris? It is.", "Is it Paris? It is."),
        ("Do you mean the city or the film?", "Do you mean the city or the film?"),
        ("Paris.", "Paris."),
    ],
)
def test_a_reply_never_ends_with_an_offer(said, kept):
    assert outgoing.without_offer(said) == kept
