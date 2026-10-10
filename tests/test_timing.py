"""Where the time went in a turn: what is recorded, and how it reads on the card."""
import asyncio
import logging
from types import SimpleNamespace

import pytest

from core import discord_utils, timing


@pytest.fixture(autouse=True)
def no_turn():
    timing.stop()
    yield
    timing.stop()


# --- recording ---------------------------------------------------------------
def test_nothing_is_recorded_outside_a_turn():
    timing.record_claude(1.0, "m")
    timing.record_tool("timer", 1.0)
    timing.record_discord(1.0)
    timing.record_rate_limit(1.0)
    timing.record_claude_retry()
    timing.mark_replied()
    assert timing.current() is None and timing.claude_retries() == 0


def test_a_turn_adds_up_what_it_is_told():
    turn = timing.start()
    timing.record_claude(1.5, "m", 100, 20, 5000, 0)
    timing.record_claude(2.0, "m", 150, 10, 5000, 0, retries=1)
    timing.record_tool("timer", 0.4)
    timing.record_tool("pin", 0.1, failed=True)
    timing.record_discord(0.2)
    timing.record_discord(0.9)
    timing.record_rate_limit(2.95)
    assert turn.claude_seconds == 3.5 and turn.tool_seconds == 0.5
    assert (turn.discord_calls, turn.slowest_discord) == (2, 0.9)
    assert turn.discord_seconds == pytest.approx(1.1)
    assert (turn.rate_limits, turn.rate_limit_seconds) == (1, 2.95)


def test_after_stop_nothing_more_is_added():
    turn = timing.start()
    timing.stop()
    timing.record_discord(1.0)
    assert turn.discord_calls == 0


def test_the_reply_time_is_marked_once():
    turn = timing.start()
    timing.mark_replied()
    first = turn.replied_after
    timing.mark_replied()
    assert first is not None and turn.replied_after == first


def test_each_task_has_its_own_turn():
    async def one(seconds: float) -> timing.Turn:
        turn = timing.start()
        await asyncio.sleep(0)
        timing.record_discord(seconds)
        return turn

    async def both():
        return await asyncio.gather(one(1.0), one(2.0))

    first, second = asyncio.run(both())
    assert (first.discord_seconds, second.discord_seconds) == (1.0, 2.0)


# --- retries and rate limits, read from the libraries' logs -------------------
@pytest.fixture
def logs_on():
    """The tests run with logging switched off (tests/__init__.py): on for these."""
    logging.disable(logging.NOTSET)
    yield
    logging.disable(logging.CRITICAL)


def test_a_discord_rate_limit_is_noticed_with_its_wait(logs_on):
    timing.watch_logs()
    turn = timing.start()
    logging.getLogger(timing.DISCORD_LOGGER).warning(
        "We are being rate limited. %s %s responded with 429. Retrying in %.2f seconds.", "PATCH", "url", 2.95
    )
    assert (turn.rate_limits, turn.rate_limit_seconds) == (1, 2.95)


def test_a_claude_retry_is_noticed(logs_on):
    timing.watch_logs()
    turn = timing.start()
    logging.getLogger(timing.CLAUDE_LOGGER).info("Retrying request to %s in %f seconds", "/v1/messages", 0.5)
    assert turn.claude_retries == 1


def test_other_log_lines_are_not_counted(logs_on):
    timing.watch_logs()
    turn = timing.start()
    logging.getLogger(timing.DISCORD_LOGGER).warning("Something else went wrong")
    logging.getLogger(timing.CLAUDE_LOGGER).info("HTTP Request: POST")
    assert (turn.rate_limits, turn.claude_retries) == (0, 0)


def test_watching_twice_counts_once(logs_on):
    timing.watch_logs()
    timing.watch_logs()
    turn = timing.start()
    logging.getLogger(timing.CLAUDE_LOGGER).info("Retrying request to %s in %f seconds", "/v1/messages", 0.5)
    assert turn.claude_retries == 1


# --- the Claude loop and the Discord client report in --------------------------


def test_discord_requests_are_timed_once_however_often_bound(monkeypatch):
    sent = []

    async def request(route):
        sent.append(route)
        return "ok"

    client = SimpleNamespace(http=SimpleNamespace(request=request))
    monkeypatch.setattr(discord_utils, "client", None)
    discord_utils.bind_client(client)
    discord_utils.bind_client(client)

    async def use() -> tuple[timing.Turn, str]:
        turn = timing.start()
        return turn, await client.http.request("route")

    turn, answer = asyncio.run(use())
    assert answer == "ok" and sent == ["route"] and turn.discord_calls == 1


def test_a_failed_discord_request_still_counts(monkeypatch):
    async def request(route):
        raise RuntimeError("gone")

    client = SimpleNamespace(http=SimpleNamespace(request=request))
    monkeypatch.setattr(discord_utils, "client", None)
    discord_utils.bind_client(client)

    async def use() -> timing.Turn:
        turn = timing.start()
        with pytest.raises(RuntimeError):
            await client.http.request("route")
        return turn

    assert asyncio.run(use()).discord_calls == 1


# --- the breakdown in words -------------------------------------------------
def _turn() -> timing.Turn:
    turn = timing.Turn()
    turn.claude_calls = [
        timing.ClaudeCall(3.41, "claude-haiku-4-5", 480, 31, 5593, 0),
        timing.ClaudeCall(3.62, "claude-haiku-4-5", 600, 12, 5593, 0, retries=1),
    ]
    turn.tool_runs = [timing.ToolRun("timer", 1.35), timing.ToolRun("pin", 0.2, failed=True)]
    turn.discord_calls, turn.discord_seconds, turn.slowest_discord = 6, 1.2, 0.9
    turn.rate_limits, turn.rate_limit_seconds, turn.claude_retries = 1, 2.95, 1
    turn.replied_after = 8.5
    return turn


def test_the_card_lists_every_request_tool_and_wait():
    lines = timing.summary_lines(_turn())
    assert lines[0] == "**8.50s** to the reply · 2 round trips to Claude"
    assert lines[1] == "1. 3.41s claude-haiku-4-5 · 480 in / 31 out · cache 5593 read / 0 written"
    assert lines[2].endswith("cache 5593 read / 0 written · 1 retry")
    assert lines[3] == "🔧 `timer` 1.35s" and lines[4] == "🔧 `pin` 0.20s (failed)"
    assert lines[5] == "Discord: 1.20s over 6 calls (slowest 0.90s)"
    assert lines[6] == "Rate-limit waits: 1 (2.95s) · Claude retries: 1"


def test_a_plain_answer_reads_as_one_round_trip():
    turn = timing.Turn()
    turn.claude_calls = [timing.ClaudeCall(1.5, "m", 100, 20)]
    turn.discord_calls, turn.discord_seconds = 1, 0.3
    lines = timing.summary_lines(turn, total=2.0)
    assert lines[0] == "**2.00s** to the reply · 1 round trip to Claude"
    assert lines[2] == "Discord: 0.30s over 1 call"


def test_the_log_line_has_the_same_numbers():
    line = timing.log_line(_turn())
    assert line.startswith("total 8.50s | claude 3.41s + 3.62s (2 round trips, 1 retries)")
    assert "tools timer 1.35s, pin 0.20s" in line
    assert line.endswith("discord 1.20s over 6 calls, 1 rate-limit waits (2.95s)")


def test_the_breakdown_is_kept_as_plain_values():
    import json

    kept = json.loads(json.dumps(timing.as_dict(_turn())))
    assert kept["total_s"] == 8.5
    assert [call["seconds"] for call in kept["claude"]] == [3.41, 3.62]
    assert kept["claude"][1]["retries"] == 1 and kept["claude"][0]["cache_read_tokens"] == 5593
    assert kept["tools"] == [
        {"name": "timer", "seconds": 1.35, "failed": False},
        {"name": "pin", "seconds": 0.2, "failed": True},
    ]
    assert (kept["discord_calls"], kept["discord_s"]) == (6, 1.2)
    assert (kept["rate_limits"], kept["rate_limit_s"], kept["claude_retries"]) == (1, 2.95, 1)
