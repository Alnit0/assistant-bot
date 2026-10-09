import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from core.config import MODEL_PRICING, TIMEZONE

# ---------------------------------------------------------------------------
# What each message cost, and by which way it was handled.
#
# Every logged message gets a route: how it was dealt with. The cheap ones
# never reach Claude; the others say how many requests they made, the tokens
# of each kind, and what that cost. `dev cost` adds it up.
#
#   button     a button, dropdown or form                       0 requests
#   shortcut   a typed word, or a word replied to a message     0
#   reaction   an emoji added to a message                      0
#   follow-up  a reply to an open card: extraction only         1
#   router     the router, then extraction for the task         2
#   chat       not for a task: a plain reply, no tools          1 or 2
#   tools      the old way: every tool sent with every message  2 or more
#
# No Discord and no clock here: rows in, numbers and words out. The functions
# that take a connection are run through database.run by their callers.
# ---------------------------------------------------------------------------
BUTTON, SHORTCUT, REACTION = "button", "shortcut", "reaction"
FOLLOW_UP, ROUTER, CHAT, TOOLS = "follow-up", "router", "chat", "tools"
ROUTES = (BUTTON, SHORTCUT, REACTION, FOLLOW_UP, ROUTER, CHAT, TOOLS)
CLAUDE_ROUTES = (FOLLOW_UP, ROUTER, CHAT, TOOLS)

# What a request to Claude was for
PURPOSE_ROUTER, PURPOSE_EXTRACTION, PURPOSE_CHAT, PURPOSE_TOOLS = "router", "extraction", "chat", "tools"

# Relative to the price of an input token
CACHE_READ_PRICE, CACHE_WRITE_PRICE = 0.1, 1.25

NO_TASK = "no task"  # a message to Claude that was for no task (chat), or from before tasks were recorded

# message_log kinds that are a word the user typed
_TYPED = frozenset({"command", "reply_action", "expected", "claimed", "slash", "context_menu"})
# Rows that are part of another message (a tool Claude ran for it): not messages themselves
_PARTS = frozenset({"tool", "undo"})


def route_for(kind: str) -> str | None:
    """The route of a logged input, from its kind, for everything that never
    reaches Claude. None for a row that is no message of its own (a tool
    call) and for chat, whose route is known only once it has been answered."""
    if kind in _PARTS or kind == "chat":
        return None
    if kind in _TYPED:
        return SHORTCUT
    if kind == "reaction":
        return REACTION
    return BUTTON


def price(
    model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0, cache_write_tokens: int = 0
) -> float | None:
    """What a request cost in USD, or None if the model's price is unknown.
    `input_tokens` does not include what was read from or written to the cache."""
    for name, (input_price, output_price) in MODEL_PRICING.items():
        if model.startswith(name):
            input_cost = (
                input_tokens + cache_read_tokens * CACHE_READ_PRICE + cache_write_tokens * CACHE_WRITE_PRICE
            ) * input_price
            return (input_cost + output_tokens * output_price) / 1_000_000
    return None


@dataclass(frozen=True)
class Call:
    """One request to Claude made while answering a message."""

    purpose: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    seconds: float = 0.0
    retries: int = 0
    task: str = ""  # the task it was made for (extraction), if one

    @property
    def cost(self) -> float | None:
        return price(self.model, self.input_tokens, self.output_tokens, self.cache_read_tokens, self.cache_write_tokens)


def calls_from(recorded, default_purpose: str) -> list[Call]:
    """The requests of a turn (core/timing.py's records) as Calls. One that
    didn't say what it was for gets `default_purpose`."""
    return [
        Call(
            getattr(entry, "purpose", "") or default_purpose,
            entry.model,
            entry.input_tokens,
            entry.output_tokens,
            entry.cache_read_tokens,
            entry.cache_write_tokens,
            entry.seconds,
            entry.retries,
            getattr(entry, "task", ""),
        )
        for entry in recorded
    ]


# ---------------------------------------------------------------------------
# Database (blocking; called through database.run)
# ---------------------------------------------------------------------------
def db_record(
    conn: sqlite3.Connection,
    row_id: int,
    route: str,
    tasks: list[str] | tuple[str, ...] = (),
    calls: list[Call] | tuple[Call, ...] = (),
    at: str = "",
) -> None:
    """Note how a logged message was handled and what it cost: its route, the
    tasks it was for, and each request made to Claude for it."""
    costs = [call.cost for call in calls]
    known = [cost for cost in costs if cost is not None]
    conn.execute(
        """
        UPDATE message_log
        SET route = ?, tasks = ?, claude_calls = ?, input_tokens = ?, output_tokens = ?,
            cache_read_tokens = ?, cache_write_tokens = ?, cost_usd = ?
        WHERE id = ?
        """,
        (
            route,
            ",".join(dict.fromkeys(task for task in tasks if task)),
            len(calls),
            sum(call.input_tokens for call in calls),
            sum(call.output_tokens for call in calls),
            sum(call.cache_read_tokens for call in calls),
            sum(call.cache_write_tokens for call in calls),
            sum(known) if known or not calls else None,
            row_id,
        ),
    )
    conn.executemany(
        """
        INSERT INTO llm_calls
            (message_log_id, at, purpose, task, model, input_tokens, output_tokens,
             cache_read_tokens, cache_write_tokens, cost_usd, seconds, retries)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row_id, at, call.purpose, call.task, call.model, call.input_tokens, call.output_tokens,
                call.cache_read_tokens, call.cache_write_tokens, cost, call.seconds, call.retries,
            )
            for call, cost in zip(calls, costs)
        ],
    )


@dataclass(frozen=True)
class Row:
    """One logged message, as `dev cost` reads it."""

    received_at: datetime
    route: str
    tasks: tuple[str, ...] = ()
    claude_calls: int | None = 0  # None for a message from before requests were counted
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float = 0.0
    seconds: float | None = None


def db_rows(conn: sqlite3.Connection, since: str) -> list[Row]:
    """Every message logged since `since` (ISO text, as received_at is stored)
    that has a route. Rows that are part of another message have none."""
    rows = conn.execute(
        """
        SELECT received_at, route, tasks, claude_calls, input_tokens, output_tokens,
               cache_read_tokens, cache_write_tokens, cost_usd, duration_s
        FROM message_log
        WHERE route IS NOT NULL AND received_at >= ?
        ORDER BY id
        """,
        (since,),
    ).fetchall()
    return [
        Row(
            datetime.fromisoformat(row[0]),
            row[1],
            tuple(task for task in (row[2] or "").split(",") if task),
            row[3] if row[3] is not None else (None if row[1] in CLAUDE_ROUTES else 0),
            row[4] or 0,
            row[5] or 0,
            row[6] or 0,
            row[7] or 0,
            row[8] or 0.0,
            row[9],
        )
        for row in rows
    ]


def db_purposes(conn: sqlite3.Connection, since: str) -> list[tuple[str, int, float]]:
    """(purpose, how many requests, what they cost) since `since`, dearest first."""
    return conn.execute(
        """
        SELECT purpose, COUNT(*), COALESCE(SUM(cost_usd), 0) FROM llm_calls
        WHERE at >= ? GROUP BY purpose ORDER BY 3 DESC, 1
        """,
        (since,),
    ).fetchall()


def db_state_sent(conn: sqlite3.Connection, since: str) -> tuple[int, int, int]:
    """How much of the tasks' state went to extraction since `since`: (messages
    that had some, lines sent, lines there were). The cap is
    `actions.STATE_LINES` a task a message; the trace of each message has its own."""
    messages = sent = total = 0
    for (kept,) in conn.execute(
        "SELECT trace FROM message_log WHERE received_at >= ? AND trace LIKE '%\"state\"%'", (since,)
    ):
        try:
            states = json.loads(kept).get("state") or {}
        except (TypeError, ValueError):
            continue
        if states:
            messages += 1
            sent += sum(state.get("sent", 0) for state in states.values())
            total += sum(state.get("total", 0) for state in states.values())
    return messages, sent, total


# ---------------------------------------------------------------------------
# Adding it up (pure)
# ---------------------------------------------------------------------------
@dataclass
class Period:
    """The messages of a day or a month, added up."""

    messages: int = 0
    to_claude: int = 0  # how many of them made at least one request
    claude_calls: int = 0
    cost: float = 0.0
    input_tokens: int = 0
    cached_tokens: int = 0  # read from the cache: the cheap ones
    cache_write_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0  # of the messages that went to Claude and were timed
    timed: int = 0
    counted: int = 0  # the messages to Claude whose requests were counted (older ones weren't)
    by_route: dict[str, list] = field(default_factory=dict)  # route -> [messages, cost]
    by_task: dict[str, float] = field(default_factory=dict)  # task -> cost

    @property
    def per_message(self) -> float:
        return self.cost / self.messages if self.messages else 0.0

    @property
    def per_claude_message(self) -> float:
        return self.cost / self.to_claude if self.to_claude else 0.0

    @property
    def calls_per_claude_message(self) -> float:
        return self.claude_calls / self.counted if self.counted else 0.0

    @property
    def seconds_per_claude_message(self) -> float:
        return self.seconds / self.timed if self.timed else 0.0

    @property
    def dearest_task(self) -> tuple[str, float] | None:
        """The task that cost most, and what it cost. None if nothing cost anything."""
        spent = {task: cost for task, cost in self.by_task.items() if cost > 0}
        if not spent:
            return None
        task = max(spent, key=lambda name: (spent[name], name != NO_TASK))
        return task, spent[task]


def add_up(rows: list[Row]) -> Period:
    period = Period()
    by_route: dict[str, list] = defaultdict(lambda: [0, 0.0])
    by_task: dict[str, float] = defaultdict(float)
    for row in rows:
        period.messages += 1
        period.cost += row.cost
        period.claude_calls += row.claude_calls or 0
        period.input_tokens += row.input_tokens
        period.cached_tokens += row.cache_read_tokens
        period.cache_write_tokens += row.cache_write_tokens
        period.output_tokens += row.output_tokens
        by_route[row.route][0] += 1
        by_route[row.route][1] += row.cost
        if row.claude_calls or row.route in CLAUDE_ROUTES:
            period.to_claude += 1
            period.counted += row.claude_calls is not None
            if row.seconds is not None:
                period.seconds += row.seconds
                period.timed += 1
            # A message for two tasks is charged half to each
            for task in row.tasks or (NO_TASK,):
                by_task[task] += row.cost / max(1, len(row.tasks))
    period.by_route, period.by_task = dict(by_route), dict(by_task)
    return period


def day_of(moment: datetime) -> date:
    """The NZ calendar day of a real moment. Costs go by the real clock, not the dev clock."""
    return moment.astimezone(TIMEZONE).date()


def month_start(now: datetime) -> datetime:
    """Midnight on the first of this month in NZ, to read rows from."""
    return now.astimezone(TIMEZONE).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def split(rows: list[Row], now: datetime) -> tuple[Period, Period]:
    """(today, this month so far) from this month's rows."""
    today, first = day_of(now), day_of(month_start(now))
    this_month = [row for row in rows if day_of(row.received_at) >= first]
    return add_up([row for row in this_month if day_of(row.received_at) == today]), add_up(this_month)


# ---------------------------------------------------------------------------
# In words
# ---------------------------------------------------------------------------
def money(cost: float | None) -> str:
    return f"US${cost:.4f}" if cost is not None else "unknown"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _period_lines(title: str, period: Period) -> list[str]:
    if not period.messages:
        return [f"**{title}** · nothing yet"]
    lines = [f"**{title}** · {money(period.cost)} · {_plural(period.messages, 'message')}, {period.to_claude} to Claude"]
    if period.to_claude:
        lines.append(
            f"-# average {money(period.per_message)} a message · {money(period.per_claude_message)}, "
            f"{period.calls_per_claude_message:.1f} requests and {period.seconds_per_claude_message:.1f}s "
            "a message to Claude"
        )
    routes = []
    for route in ROUTES:
        if route in period.by_route:
            count, cost = period.by_route[route]
            routes.append(f"{route} {count}" + (f" ({money(cost)})" if cost else ""))
    lines.append("-# " + " · ".join(routes))
    return lines


def report(
    today: Period, month: Period, purposes: list[tuple[str, int, float]], database_name: str,
    state: tuple[int, int, int] = (0, 0, 0), state_cap: int = 0,
) -> str:
    """What `dev cost` shows: today, this month, the average per message, the
    most expensive task, and where the requests to Claude went."""
    lines = [f"## 💰 Cost · `{database_name}`", *_period_lines("Today", today), *_period_lines("This month", month)]
    dearest = month.dearest_task
    if dearest is not None:
        task, cost = dearest
        share = f" ({cost / month.cost:.0%} of the month)" if month.cost else ""
        lines.append(f"Most expensive task this month: **{task}** · {money(cost)}{share}")
        others = sorted(((name, spent) for name, spent in month.by_task.items() if name != task and spent > 0), key=lambda entry: -entry[1])
        if others:
            lines.append("-# then " + " · ".join(f"{name} {money(spent)}" for name, spent in others[:5]))
    if month.to_claude:
        lines.append(
            f"-# Tokens this month: {month.input_tokens:,} in · {month.cached_tokens:,} read from cache · "
            f"{month.cache_write_tokens:,} written to it · {month.output_tokens:,} out"
        )
    if purposes:
        lines.append(
            "-# Requests this month: "
            + " · ".join(f"{purpose} {count} ({money(cost)})" for purpose, count, cost in purposes)
        )
    messages, sent, total = state
    if messages:
        held_back = f", {total - sent:,} held back by the cap" if total > sent else ", nothing held back"
        lines.append(
            f"-# List context sent to extraction this month: {sent:,} of {total:,} lines over "
            f"{_plural(messages, 'message')}{held_back} (at most {state_cap} a task a message)"
        )
    return "\n".join(lines)
