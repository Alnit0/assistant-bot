from datetime import datetime, timedelta, timezone

import pytest

from core import pending

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
CHANNEL, USER = 100, 1


@pytest.fixture(autouse=True)
def nothing_pending():
    pending.clear()
    yield
    pending.clear()


# --- is it an answer? --------------------------------------------------------
@pytest.mark.parametrize("text", ["ok", "OK", "Yes", "yep", "do it", "Do it!", "go ahead", "  sure. ", "yes please", "👍"])
def test_short_agreements_are_a_yes(text):
    assert pending.classify(text) == pending.YES


@pytest.mark.parametrize("text", ["no", "Nope", "cancel", "never mind", "don't", "no thanks."])
def test_short_refusals_are_a_no(text):
    assert pending.classify(text) == pending.NO


@pytest.mark.parametrize("text", ["ok but make it 10 minutes", "yes and also pin it", "what?", "okay then what about lunch", ""])
def test_anything_longer_is_not_an_answer(text):
    assert pending.classify(text) is None


# --- remembering what was proposed -------------------------------------------
def test_a_proposal_is_there_to_be_taken_once():
    pending.propose(CHANNEL, USER, "call", "`timer 5m`", NOW)
    taken = pending.take(CHANNEL, USER, NOW + timedelta(seconds=30))
    assert (taken.call, taken.summary) == ("call", "`timer 5m`")
    assert pending.take(CHANNEL, USER, NOW + timedelta(seconds=31)) is None


def test_it_lasts_two_minutes():
    pending.propose(CHANNEL, USER, "call", "x", NOW)
    assert pending.take(CHANNEL, USER, NOW + timedelta(seconds=119)) is not None
    pending.propose(CHANNEL, USER, "call", "x", NOW)
    assert pending.take(CHANNEL, USER, NOW + timedelta(seconds=120)) is None
    assert pending.take(CHANNEL, USER, NOW) is None, "an expired one is gone, not waiting"


def test_a_new_proposal_replaces_the_old_one():
    pending.propose(CHANNEL, USER, "first", "first", NOW)
    pending.propose(CHANNEL, USER, "second", "second", NOW)
    assert pending.take(CHANNEL, USER, NOW).call == "second"


def test_proposals_belong_to_one_user_in_one_channel():
    pending.propose(CHANNEL, USER, "call", "x", NOW)
    assert pending.take(200, USER, NOW) is None
    assert pending.take(CHANNEL, 2, NOW) is None
    assert pending.take(CHANNEL, USER, NOW) is not None
