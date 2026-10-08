import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Where the time goes while one message is being answered: each request to
# Claude, each tool, the calls to Discord, and anything that had to wait and
# try again. No Discord or API calls here: the code that makes them reports
# how long they took, and the #bot-log card shows the breakdown.
#
# One Turn per message, found through a context variable, so nothing has to
# be passed down through the tool loop and the tasks. Outside a turn (jobs,
# buttons, tests) every `record_*` does nothing.
# ---------------------------------------------------------------------------
CLAUDE_LOGGER = "anthropic._base_client"  # logs "Retrying request to %s in %f seconds"
DISCORD_LOGGER = "discord.http"  # logs "We are being rate limited. ... Retrying in %.2f seconds."


@dataclass(frozen=True)
class ClaudeCall:
    seconds: float
    model: str
    input_tokens: int = 0  # not counting what was read from or written to the cache
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    retries: int = 0


@dataclass(frozen=True)
class ToolRun:
    name: str
    seconds: float
    failed: bool = False


@dataclass
class Turn:
    started: float = field(default_factory=time.perf_counter)
    claude_calls: list[ClaudeCall] = field(default_factory=list)
    tool_runs: list[ToolRun] = field(default_factory=list)
    discord_calls: int = 0
    discord_seconds: float = 0.0  # includes any waiting for a rate limit
    slowest_discord: float = 0.0
    rate_limits: int = 0
    rate_limit_seconds: float = 0.0
    claude_retries: int = 0
    replied_after: float | None = None  # seconds from the start until the reply was sent

    @property
    def claude_seconds(self) -> float:
        return sum(call.seconds for call in self.claude_calls)

    @property
    def tool_seconds(self) -> float:
        return sum(run.seconds for run in self.tool_runs)

    def elapsed(self) -> float:
        return time.perf_counter() - self.started


_current: ContextVar[Turn | None] = ContextVar("timing_turn", default=None)


def start() -> Turn:
    """Begin timing the message being answered here (each asyncio task has its own turn)."""
    turn = Turn()
    _current.set(turn)
    return turn


def stop() -> None:
    """Stop recording: what happens from here on is not part of the turn."""
    _current.set(None)


def current() -> Turn | None:
    return _current.get()


def record_claude(
    seconds: float,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    retries: int = 0,
) -> None:
    turn = _current.get()
    if turn is not None:
        turn.claude_calls.append(
            ClaudeCall(seconds, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, retries)
        )


def record_tool(name: str, seconds: float, failed: bool = False) -> None:
    turn = _current.get()
    if turn is not None:
        turn.tool_runs.append(ToolRun(name, seconds, failed))


def record_discord(seconds: float) -> None:
    turn = _current.get()
    if turn is not None:
        turn.discord_calls += 1
        turn.discord_seconds += seconds
        turn.slowest_discord = max(turn.slowest_discord, seconds)


def record_rate_limit(seconds: float) -> None:
    turn = _current.get()
    if turn is not None:
        turn.rate_limits += 1
        turn.rate_limit_seconds += seconds


def record_claude_retry() -> None:
    turn = _current.get()
    if turn is not None:
        turn.claude_retries += 1


def claude_retries() -> int:
    """How many times a request to Claude has been retried so far this turn."""
    turn = _current.get()
    return turn.claude_retries if turn is not None else 0


def mark_replied() -> None:
    turn = _current.get()
    if turn is not None and turn.replied_after is None:
        turn.replied_after = turn.elapsed()


# ---------------------------------------------------------------------------
# Retries and rate limits. Neither library says when it waits and tries again
# except in its log, so that is where they are read from.
# ---------------------------------------------------------------------------
def _wait_in(record: logging.LogRecord) -> float:
    """The seconds a "Retrying in ..." log line says it will wait (its last argument)."""
    args = record.args if isinstance(record.args, tuple) else ()
    return float(args[-1]) if args and isinstance(args[-1], (int, float)) else 0.0


class _Waits(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = str(record.msg)
            if record.name == CLAUDE_LOGGER and text.startswith("Retrying request"):
                record_claude_retry()
            elif record.name == DISCORD_LOGGER and "Retrying in" in text:
                record_rate_limit(_wait_in(record))
        except Exception:
            self.handleError(record)


_waits = _Waits(level=logging.INFO)


def watch_logs() -> None:
    """Start noticing Claude retries and Discord rate limits. Safe to call twice."""
    for name in (CLAUDE_LOGGER, DISCORD_LOGGER):
        logger = logging.getLogger(name)
        if _waits not in logger.handlers:
            logger.addHandler(_waits)
        if logger.getEffectiveLevel() > logging.INFO:
            logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# The breakdown in words
# ---------------------------------------------------------------------------
def _seconds(value: float) -> str:
    return f"{value:.2f}s"


def summary_lines(turn: Turn, total: float | None = None) -> list[str]:
    """The breakdown for the #bot-log card, one short line per thing timed.

    `total` is the whole turn in seconds; by default, until the reply was sent.
    Tools' times include the Discord calls they made, so "Discord" overlaps
    with them rather than adding to the total.
    """
    if total is None:
        total = turn.replied_after if turn.replied_after is not None else turn.elapsed()
    trips = len(turn.claude_calls)
    lines = [f"**{_seconds(total)}** to the reply · {trips} round trip{'' if trips == 1 else 's'} to Claude"]
    for number, call in enumerate(turn.claude_calls, start=1):
        retried = f" · {call.retries} retr{'y' if call.retries == 1 else 'ies'}" if call.retries else ""
        lines.append(
            f"{number}. {_seconds(call.seconds)} {call.model} · {call.input_tokens} in / {call.output_tokens} out"
            f" · cache {call.cache_read_tokens} read / {call.cache_write_tokens} written{retried}"
        )
    for run in turn.tool_runs:
        lines.append(f"🔧 `{run.name}` {_seconds(run.seconds)}{' (failed)' if run.failed else ''}")
    lines.append(
        f"Discord: {_seconds(turn.discord_seconds)} over {turn.discord_calls} call{'' if turn.discord_calls == 1 else 's'}"
        + (f" (slowest {_seconds(turn.slowest_discord)})" if turn.discord_calls > 1 else "")
    )
    lines.append(
        f"Rate-limit waits: {turn.rate_limits} ({_seconds(turn.rate_limit_seconds)}) · Claude retries: {turn.claude_retries}"
    )
    return lines


def log_line(turn: Turn, total: float | None = None) -> str:
    """The same breakdown on one line, for bot.log."""
    if total is None:
        total = turn.replied_after if turn.replied_after is not None else turn.elapsed()
    claude = " + ".join(_seconds(call.seconds) for call in turn.claude_calls) or "none"
    tools = ", ".join(f"{run.name} {_seconds(run.seconds)}" for run in turn.tool_runs) or "none"
    return (
        f"total {_seconds(total)} | claude {claude} ({len(turn.claude_calls)} round trips, "
        f"{turn.claude_retries} retries) | tools {tools} | discord {_seconds(turn.discord_seconds)} over "
        f"{turn.discord_calls} calls, {turn.rate_limits} rate-limit waits ({_seconds(turn.rate_limit_seconds)})"
    )
