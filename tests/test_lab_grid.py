"""The lab's animated grid, a proof of concept (tasks/lab/grid.py, tasks/lab/animate.py; behind LAB_GRID, off):
the frames, the seconds between them, one at a time across the bot, and a run that stops at the first edit that
fails or is rate-limited. No Discord here: the door is stood in for."""
import asyncio
from types import SimpleNamespace

import pytest

from core import config, surface
from tasks.lab import animate, grid, ratelimits

RAINBOW = ["🟥", "🟧", "🟨", "🟩", "🟦", "🟪"]


# --- the frames -------------------------------------------------------------------------------------------------------
def test_frame_0_is_all_black_and_frame_9_all_green():
    assert grid.squares(0) == ["⬛"] * 25 and grid.squares(9) == ["🟩"] * 25


def test_the_palette_is_red_orange_yellow_green_blue_purple_in_that_order():
    assert list(grid.PALETTE) == RAINBOW


def test_a_wave_frame_rolls_the_palette_diagonally():
    for frame in range(1, 9):
        found = grid.squares(frame)
        assert len(found) == 25
        for row in range(5):
            for column in range(5):
                assert found[row * 5 + column] == RAINBOW[(row + column + frame) % 6]
    assert grid.squares(1)[0] == "🟧" and grid.squares(1)[1] == grid.squares(1)[5] == "🟨", "the diagonal shares a colour"


def test_a_frame_is_an_invisible_first_line_then_five_rows_of_five_squares_and_nothing_else():
    """The first line is a zero-width space alone: Compact display puts a first line beside the bot's name (21 Oct)."""
    for frame in range(10):
        first, *rows = grid.frame_text(frame).split("\n")
        assert first == "​"
        assert len(rows) == 5 and all(len(row) == 5 for row in rows), "five squares a row, no text, no spaces"
        assert rows == ["".join(grid.squares(frame)[index * 5:(index + 1) * 5]) for index in range(5)]


def test_there_are_ten_frames_in_all():
    assert grid.LAST == 9 and grid.WAVES == 8


# --- the seconds between frames ------------------------------------------------------------------------------------
@pytest.mark.parametrize("said, wanted", [(None, 1.0), ("", 1.0), ("0.5", 0.5), ("2", 2.0), ("0.1", 0.5), ("10", 3.0), ("fast", 1.0), ("nan", 1.0), ("-1", 0.5), ("3.0", 3.0)])
def test_the_seconds_are_one_unless_said_and_kept_between_half_and_three(said, wanted):
    assert grid.seconds(said) == wanted


# --- one at a time ------------------------------------------------------------------------------------------------------
def test_one_grid_at_a_time():
    lock = grid.OneAtATime()
    assert lock.take() and not lock.take(), "a second waits for nothing: it is refused"
    lock.release()
    assert lock.take()


# --- a run, through a stand-in door ---------------------------------------------------------------------------------
@pytest.fixture
def door(monkeypatch):
    seen = SimpleNamespace(posted=[], edited=[], fail_at=None, limit_at=None)

    async def send(channel_id, text, *, silent=False, suppress_embeds=False):
        seen.posted.append((channel_id, text, silent))
        return 4242

    async def edit(channel_id, message_id, text, *, suppress_embeds=False):
        frame = len(seen.edited) + 1
        if seen.fail_at == frame:
            raise surface.Failed("made-up failure", 500)
        if seen.limit_at == frame:
            ratelimits.monitor.count += 1  # what discord.py's warning does, through the lab's monitor
        seen.edited.append((message_id, text))

    async def no_wait(seconds):
        seen.waits = getattr(seen, "waits", []) + [seconds]

    monkeypatch.setattr(surface, "send", send)
    monkeypatch.setattr(surface, "edit", edit)
    monkeypatch.setattr(animate.asyncio, "sleep", no_wait)
    return seen


def test_a_run_posts_frame_0_then_edits_the_same_message_through_frame_9(door):
    run = asyncio.run(animate.animate(77, 0.5))
    assert door.posted == [(77, grid.frame_text(0), True)]
    assert [text for _, text in door.edited] == [grid.frame_text(frame) for frame in range(1, 10)]
    assert {message_id for message_id, _ in door.edited} == {4242}, "one message, edited"
    assert run.finished and run.frames == 10 and len(run.gaps) == 9 and run.failed == run.limited == 0
    assert door.waits == [0.5] * 9, "a wait before each edit, never two at once"


def test_an_edit_that_fails_stops_it_at_once_and_is_never_tried_again(door):
    door.fail_at = 4
    run = asyncio.run(animate.animate(77, 1.0))
    assert len(door.edited) == 3 and run.failed == 1 and not run.finished and run.frames == 4
    assert "stopped early" in run.line()


def test_an_edit_that_was_rate_limited_stops_it_there(door):
    door.limit_at = 2
    run = asyncio.run(animate.animate(77, 1.0))
    assert len(door.edited) == 2 and run.limited == 1 and not run.finished


def test_the_measurements_are_the_average_and_the_slowest_gap():
    run = grid.Run(1.0, gaps=[1.1, 1.3, 1.2], frames=10)
    assert round(run.average, 2) == 1.2 and run.slowest == 1.3
    assert run.line() == "lab grid at 1.0s: 10 of 10 frames, gap 1.20s on average, 1.30s at most; 0 rate-limited, 0 failed"


def test_lab_grid_while_one_runs_gets_a_short_line_that_goes_and_starts_nothing(door, monkeypatch):
    from core import cards, tidy

    said, later = [], []

    async def send_card(channel_id, card, silent=False):
        said.append(card.text)
        return 99

    async def tidy_later(channel_id, message_id, seconds):
        later.append(message_id)

    monkeypatch.setattr(cards, "send", send_card)
    monkeypatch.setattr(tidy, "later", tidy_later)
    monkeypatch.setattr(animate, "lock", grid.OneAtATime())
    animate.lock.take()  # one is running
    ctx = SimpleNamespace(args=["0.5"], channel_id=77)
    assert asyncio.run(animate.run_grid(ctx)) == "a grid is running already"
    assert said == [animate.BUSY] and later == [99] and door.posted == [], "a line that deletes itself, and no grid"


def test_lab_grid_starts_the_run_and_answers_at_once_then_lets_the_next_one_run(door, monkeypatch):
    monkeypatch.setattr(animate, "lock", grid.OneAtATime())

    async def typed():
        said = await animate.run_grid(SimpleNamespace(args=[], channel_id=77))
        await asyncio.gather(*animate._running)
        return said

    assert asyncio.run(typed()) == "grid started, 1.0s a frame"
    assert len(door.edited) == 9 and not animate.lock.running, "the lock is let go when it ends"


def test_the_word_is_only_there_with_lab_grid_on(monkeypatch):
    from tasks import lab

    monkeypatch.setattr(config, "LAB_GRID", False)
    assert "lab grid" not in [word for each in lab.task.keywords() for word in ([each.words] if isinstance(each.words, str) else each.words)]
    monkeypatch.setattr(config, "LAB_GRID", True)
    (found,) = [each for each in lab.task.keywords() if "lab grid" in ([each.words] if isinstance(each.words, str) else each.words)]
    assert found.permission == "lab" and found.takes_args and found.usage == "[seconds]" and found.exact


def test_the_word_answers_in_every_channel_and_in_a_direct_message(monkeypatch):
    """Alex, 21 Oct: on live, from his phone, wherever he is. Its registration says anywhere."""
    from core import dms
    from tasks import lab, registry

    monkeypatch.setattr(config, "LAB_GRID", True)
    (found,) = [each for each in lab.task.keywords() if "lab grid" in ([each.words] if isinstance(each.words, str) else each.words)]
    assert registry.where(found) == "anywhere"
    assert registry.works_in(found, 123456) and registry.works_in(found, config.INBOX_CHANNEL_ID)
    monkeypatch.setattr(dms, "is_dm", lambda channel_id: channel_id == 777)
    assert registry.works_in(found, 777), "a direct message too"


def test_off_unless_switched_on():
    assert config.LAB_GRID is False
