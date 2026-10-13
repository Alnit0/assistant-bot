"""What each message cost and how it was handled (core/costs.py), and `dev cost`."""
import asyncio
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core import cards, costs, database, migrations, timing
from core.config import TIMEZONE
from core.costs import BUTTON, CHAT, FOLLOW_UP, REACTION, ROUTER, SHORTCUT, TOOLS, Call, Row

HAIKU = "claude-haiku-4-5"  # NZ$1 a million in, NZ$5 out, in the test settings as in the real ones


def nz(*parts) -> datetime:
    return datetime(*parts, tzinfo=TIMEZONE)


NOW = nz(2026, 10, 9, 15, 0)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind, route",
    [
        ("command", SHORTCUT),
        ("reply_action", SHORTCUT),
        ("expected", SHORTCUT),
        ("claimed", SHORTCUT),
        ("reaction", REACTION),
        ("card", BUTTON),
        ("confirmation", BUTTON),
        ("timers", BUTTON),  # a task's own buttons are logged under its name
        ("dev", BUTTON),
        ("chat", None),  # known only once it has been answered
        ("tool", None),  # part of another message, not one of its own
    ],
)
def test_what_never_reaches_claude_gets_its_route_from_its_kind(kind, route):
    assert costs.route_for(kind) == route


def test_every_logged_input_is_given_its_route_as_it_arrives(db):
    async def scenario():
        typed = await database.log_received("timers", "command", 1, 100, user_id=1)
        pressed = await database.log_received("card: pills/save 1", "card", 2, 100, user_id=1)
        chat = await database.log_received("hello", "chat", 3, 100, user_id=1)
        part = await database.log_received("tool: timer {}", "tool", 3, 100, user_id=1)
        return typed, pressed, chat, part

    ids = asyncio.run(scenario())
    conn = database.connect()
    routes = dict(conn.execute("SELECT id, route FROM message_log").fetchall())
    conn.close()
    assert [routes[row_id] for row_id in ids] == [SHORTCUT, BUTTON, None, None]


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
def test_cached_tokens_cost_a_tenth_to_read_and_a_quarter_more_to_write():
    assert costs.price(HAIKU, 1_000_000, 0) == pytest.approx(1.00)
    assert costs.price(HAIKU, 0, 1_000_000) == pytest.approx(5.00)
    assert costs.price(HAIKU, 0, 0, cache_read_tokens=1_000_000) == pytest.approx(0.10)
    assert costs.price(HAIKU, 0, 0, cache_write_tokens=1_000_000) == pytest.approx(1.25)
    assert costs.price(HAIKU, 1067, 238, 9833, 9833) == pytest.approx((1067 + 983.3 + 12291.25 + 238 * 5) / 1e6)


def test_a_model_with_no_known_price_costs_unknown_not_nothing():
    assert costs.price("some-new-model", 1000, 1000) is None
    assert Call("router", "some-new-model", 1000, 10).cost is None
    assert costs.money(None) == "unknown" and costs.money(0.0421) == "NZ$0.0421"


def test_the_requests_of_a_turn_become_calls_with_what_they_were_for():
    turn = timing.start()
    timing.record_claude(0.8, HAIKU, 500, 30, 9000, 0, purpose="router")
    timing.record_claude(1.2, HAIKU, 700, 80, 0, 0, retries=1, purpose="extraction", task="pills")
    timing.record_claude(2.0, HAIKU, 1000, 200)  # the old path doesn't say
    timing.stop()
    calls = costs.calls_from(turn.claude_calls, costs.PURPOSE_TOOLS)
    assert [(call.purpose, call.task, call.seconds, call.retries) for call in calls] == [
        ("router", "", 0.8, 0), ("extraction", "pills", 1.2, 1), ("tools", "", 2.0, 0),
    ]
    assert calls[0].cost == pytest.approx((500 + 900) / 1e6 + 30 * 5 / 1e6)


# ---------------------------------------------------------------------------
# Recording a message, and reading it back
# ---------------------------------------------------------------------------
def test_a_message_is_recorded_with_its_route_tasks_and_every_request(db):
    calls = [
        Call("router", HAIKU, 500, 30, cache_read_tokens=9000, seconds=0.8),
        Call("extraction", HAIKU, 700, 80, cache_write_tokens=400, seconds=1.2, task="pills"),
    ]

    async def scenario():
        row_id = await database.log_received("add vitamin D", "chat", 5, 100, user_id=1)
        await database.log_result(row_id, reply="shown", status="ok", duration_s=2.4)
        await database.record_cost(row_id, ROUTER, ["pills", "", "pills"], calls)
        since = (datetime.now(TIMEZONE) - timedelta(days=1)).isoformat()
        return row_id, await database.run(costs.db_rows, since), await database.run(costs.db_purposes, since)

    row_id, rows, purposes = asyncio.run(scenario())
    (row,) = rows
    total = sum(call.cost for call in calls)
    assert (row.route, row.tasks, row.claude_calls, row.seconds) == (ROUTER, ("pills",), 2, 2.4)
    assert (row.input_tokens, row.output_tokens, row.cache_read_tokens, row.cache_write_tokens) == (1200, 110, 9000, 400)
    assert row.cost == pytest.approx(total)
    assert [(purpose, count) for purpose, count, _ in purposes] == [("extraction", 1), ("router", 1)]
    assert sum(cost for _, _, cost in purposes) == pytest.approx(total)

    conn = database.connect()
    stored = conn.execute("SELECT message_log_id, purpose, task, model, seconds FROM llm_calls ORDER BY id").fetchall()
    conn.close()
    assert stored == [(row_id, "router", "", HAIKU, 0.8), (row_id, "extraction", "pills", HAIKU, 1.2)]


def test_a_message_that_made_no_request_costs_nothing_and_parts_are_not_messages(db):
    async def scenario():
        await database.log_received("timers", "command", 1, 100, user_id=1)
        await database.log_received("tool: timer {}", "tool", 1, 100, user_id=1)
        return await database.run(costs.db_rows, "2000-01-01")

    (row,) = asyncio.run(scenario())
    assert (row.route, row.cost, row.claude_calls, row.tasks) == (SHORTCUT, 0.0, 0, ())


# ---------------------------------------------------------------------------
# Adding it up
# ---------------------------------------------------------------------------
def row(when, route, cost=0.0, tasks=(), calls=0, seconds=None, tokens=(0, 0, 0, 0)):
    return Row(when, route, tuple(tasks), calls, tokens[0], tokens[3], tokens[1], tokens[2], cost, seconds)


ROWS = [
    # earlier this month
    row(nz(2026, 10, 2, 9, 0), TOOLS, 0.0100, ["timers"], 2, 4.0, (1000, 9000, 0, 200)),
    row(nz(2026, 10, 2, 9, 5), SHORTCUT),
    row(nz(2026, 10, 8, 23, 59), TOOLS, 0.0300, ["pills", "timers"], 3, 6.0, (2000, 9000, 0, 300)),
    # today
    row(nz(2026, 10, 9, 0, 0), SHORTCUT, seconds=0.2),
    row(nz(2026, 10, 9, 8, 0), BUTTON),
    row(nz(2026, 10, 9, 8, 1), REACTION),
    row(nz(2026, 10, 9, 9, 0), ROUTER, 0.0040, ["pills"], 2, 2.0, (800, 5000, 100, 90)),
    row(nz(2026, 10, 9, 9, 5), FOLLOW_UP, 0.0010, ["pills"], 1, 1.0, (300, 2000, 0, 40)),
    row(nz(2026, 10, 9, 9, 9), CHAT, 0.0020, [], 2, 3.0, (500, 0, 0, 150)),
]


def test_today_and_the_month_are_split_at_midnight_nz():
    today, month = costs.split(ROWS, NOW)
    assert (today.messages, today.to_claude, today.claude_calls) == (6, 3, 5)
    assert today.cost == pytest.approx(0.0070)
    assert (month.messages, month.to_claude, month.claude_calls) == (9, 5, 10)
    assert month.cost == pytest.approx(0.0470)


def test_last_months_rows_are_not_this_months():
    rows = [row(nz(2026, 9, 30, 23, 59), TOOLS, 1.0, calls=2), *ROWS]
    _, month = costs.split(rows, NOW)
    assert month.cost == pytest.approx(0.0470)
    assert costs.month_start(NOW) == nz(2026, 10, 1, 0, 0)


def test_averages_are_per_message_and_per_message_to_claude():
    today, _ = costs.split(ROWS, NOW)
    assert today.per_message == pytest.approx(0.0070 / 6)
    assert today.per_claude_message == pytest.approx(0.0070 / 3)
    assert today.calls_per_claude_message == pytest.approx(5 / 3)
    assert today.seconds_per_claude_message == pytest.approx(2.0), "the shortcut's 0.2s is not part of Claude's average"


def test_messages_from_before_requests_were_counted_do_not_drag_the_average_down():
    rows = [
        Row(NOW, TOOLS, claude_calls=None, cost=0.003, seconds=5.0),
        Row(NOW, TOOLS, claude_calls=None, cost=0.003, seconds=5.0),
        Row(NOW, TOOLS, claude_calls=2, cost=0.004, seconds=3.0),
    ]
    period = costs.add_up(rows)
    assert (period.to_claude, period.counted, period.claude_calls) == (3, 1, 2)
    assert period.calls_per_claude_message == 2.0, "the average of the ones that were counted"
    assert period.per_claude_message == pytest.approx(0.010 / 3), "the cost was always recorded"


def test_messages_and_cost_are_counted_by_route():
    today, _ = costs.split(ROWS, NOW)
    assert {route: (count, round(cost, 4)) for route, (count, cost) in today.by_route.items()} == {
        SHORTCUT: (1, 0.0), BUTTON: (1, 0.0), REACTION: (1, 0.0), ROUTER: (1, 0.004), FOLLOW_UP: (1, 0.001), CHAT: (1, 0.002),
    }


def test_the_most_expensive_task_shares_a_message_between_its_tasks():
    _, month = costs.split(ROWS, NOW)
    # timers: 0.01 + half of 0.03; pills: half of 0.03 + 0.004 + 0.001; chat for no task: 0.002
    assert month.by_task == pytest.approx({"timers": 0.025, "pills": 0.020, costs.NO_TASK: 0.002})
    assert month.dearest_task == ("timers", pytest.approx(0.025))
    assert costs.add_up([row(NOW, SHORTCUT)]).dearest_task is None, "nothing cost anything"


def test_tokens_are_added_up_by_kind():
    _, month = costs.split(ROWS, NOW)
    assert (month.input_tokens, month.cached_tokens, month.cache_write_tokens, month.output_tokens) == (4600, 25000, 100, 780)


def test_the_report_gives_today_the_month_the_averages_and_the_dearest_task():
    today, month = costs.split(ROWS, NOW)
    text = costs.report(today, month, [("tools", 5, 0.04), ("router", 1, 0.002)], "assistant.db")
    assert text.splitlines()[-1] == "-# Shown in NZ$, recorded in US$: US$1 = NZ$1.0000 (USD_TO_NZD in .env: no rate has been fetched yet)"
    assert text.splitlines()[:-1] == [
        "## 💰 Cost · `assistant.db`",
        "**Today** · NZ$0.0070 · 6 messages, 3 to Claude",
        "-# average NZ$0.0012 a message · NZ$0.0023, 1.7 requests and 2.0s a message to Claude",
        "-# button 1 · shortcut 1 · reaction 1 · follow-up 1 (NZ$0.0010) · router 1 (NZ$0.0040) · chat 1 (NZ$0.0020)",
        "**This month** · NZ$0.0470 · 9 messages, 5 to Claude",
        "-# average NZ$0.0052 a message · NZ$0.0094, 2.0 requests and 3.2s a message to Claude",
        "-# button 1 · shortcut 2 · reaction 1 · follow-up 1 (NZ$0.0010) · router 1 (NZ$0.0040) · chat 1 (NZ$0.0020) · tools 2 (NZ$0.0400)",
        "Most expensive task this month: **timers** · NZ$0.0250 (53% of the month)",
        "-# then pills NZ$0.0200 · no task NZ$0.0020",
        "-# Tokens this month: 4,600 in · 25,000 read from cache · 100 written to it · 780 out",
        "-# Requests this month: tools 5 (NZ$0.0400) · router 1 (NZ$0.0020)",
    ]


def test_with_nothing_logged_the_report_says_so():
    empty = costs.add_up([])
    assert costs.report(empty, empty, [], "dev.db").splitlines()[:-1] == [
        "## 💰 Cost · `dev.db`", "**Today** · nothing yet", "**This month** · nothing yet",
    ]


# ---------------------------------------------------------------------------
# What was logged before routes existed
# ---------------------------------------------------------------------------
def test_the_migration_gives_what_is_already_logged_a_route_and_its_cache_tokens(tmp_path):
    conn = sqlite3.connect(tmp_path / "old.db")
    for migration in migrations.MIGRATIONS[: migrations.MIGRATIONS.index(migrations._add_cost_logging)]:
        if migration.__name__ != "_add_user_id_to_message_log":  # needs the settings' owner; not what is tested here
            migration(conn)
    timing_json = (
        '{"total_s": 3.9, "claude": [{"seconds": 2.5, "cache_read_tokens": 9833, "cache_write_tokens": 0}, '
        '{"seconds": 1.0, "cache_read_tokens": 9833, "cache_write_tokens": 120}]}'
    )
    old = [
        ("command", "timers", "listed", "ok", None),
        ("reply_action", "pin", "pinned", "ok", None),
        ("reaction", "📦", "archived", "ok", None),
        ("timers", "button: dismiss", "dismissed", "ok", None),
        ("chat", "set a timer", "Started.\n[tools: timer]", "ok", timing_json),
        ("chat", "hello", "Hi!", "ok", None),
        ("chat", "hello?", None, "error", None),
        ("tool", "tool: timer {}", "started", "ok", None),
    ]
    conn.executemany(
        "INSERT INTO message_log (received_at, kind, content, reply, status, timing) VALUES ('2026-10-07T12:00:00+13:00', ?, ?, ?, ?, ?)",
        old,
    )
    migrations._add_cost_logging(conn)
    rows = conn.execute("SELECT kind, content, route, claude_calls, cache_read_tokens, cache_write_tokens FROM message_log ORDER BY id").fetchall()
    conn.close()
    assert [(kind, content, route) for kind, content, route, *_ in rows] == [
        ("command", "timers", SHORTCUT),
        ("reply_action", "pin", SHORTCUT),
        ("reaction", "📦", REACTION),
        ("timers", "button: dismiss", BUTTON),
        ("chat", "set a timer", TOOLS),
        ("chat", "hello", TOOLS),  # every answered chat was sent every tool, used or not
        ("chat", "hello?", CHAT),
        ("tool", "tool: timer {}", None),
    ]
    assert rows[4][3:] == (2, 19666, 120), "requests and cache tokens come from the stored timings"
    assert rows[0][3:] == (None, None, None)


# ---------------------------------------------------------------------------
# The paths that log
# ---------------------------------------------------------------------------
def test_a_typed_word_is_a_shortcut_with_its_time(db, owner):
    from core.context import Context
    from tasks import registry

    class Channel:
        id = 100

        async def send(self, text, **options):
            return SimpleNamespace(id=1)

    async def scenario():
        ctx = Context(owner, 100, None, "ping", Channel())

        async def call():
            await ctx.reply("🏓 Pong!")

        await registry._run(ctx, kind="command", name="ping", title="ping", permission="keyword:ping", call=call, keep_command=True)
        return await database.run(costs.db_rows, "2000-01-01")

    (row,) = asyncio.run(scenario())
    assert row.route == SHORTCUT and row.cost == 0.0 and row.seconds is not None


def test_a_button_press_is_a_button_with_its_time(db, monkeypatch):
    monkeypatch.setattr(cards, "_actions", {})

    async def on_press(press):
        return "pressed"

    cards.register("pills", "save", on_press)

    class Response:
        done = False

        def is_done(self):
            return self.done

        async def defer(self):
            self.done = True

    interaction = SimpleNamespace(user=SimpleNamespace(id=1), channel_id=100, message=SimpleNamespace(id=5), data={}, response=Response())

    async def scenario():
        await cards.handle(interaction, "pills", "save", "1")
        return await database.run(costs.db_rows, "2000-01-01")

    (row,) = asyncio.run(scenario())
    assert row.route == BUTTON and row.claude_calls == 0 and row.seconds is not None


def test_dev_cost_reports_this_database(db):
    from tasks.dev import tools

    said = []

    async def reply(text):
        said.append(text)

    async def scenario():
        row_id = await database.log_received("set a timer", "chat", 5, 100, user_id=1)
        await database.log_result(row_id, reply="started", status="ok", duration_s=3.0)
        await database.record_cost(row_id, TOOLS, ["timers"], [Call("tools", HAIKU, 1000, 100), Call("tools", HAIKU, 1200, 20)])
        await database.log_received("timers", "command", 6, 100, user_id=1)
        return await tools.cost(SimpleNamespace(db=database, reply=reply))

    result = asyncio.run(scenario())
    lines = said[0].splitlines()
    assert lines[0] == "## 💰 Cost · `test.db`"
    assert lines[1] == "**Today** · NZ$0.0028 · 2 messages, 1 to Claude"
    assert "2.0 requests and 3.0s a message to Claude" in lines[2]
    assert lines[3] == "-# shortcut 1 · tools 1 (NZ$0.0028)"
    assert "Most expensive task this month: **timers** · NZ$0.0028 (100% of the month)" in said[0]
    assert "-# Requests this month: tools 2 (NZ$0.0028)" in said[0]
    assert result.startswith("today NZ$0.0028 over 2 message(s)")


def test_dev_cost_is_a_typed_word():
    from tasks import registry

    registry.load()
    assert registry._keyword_router.match("dev cost").entry[1].name == "dev cost"


def test_the_report_says_how_much_list_context_went_to_extraction():
    month = costs.add_up([Row(NOW, ROUTER, ("shopping",), 2, 3000, 100, 0, 0, 0.004, 2.0)])
    text = costs.report(month, month, [], "dev.db", (3, 45, 190), 20)
    assert text.splitlines()[-1] == (
        "-# List context sent to extraction this month: 45 of 190 lines over 3 messages, 145 held back by the cap "
        "(at most 20 a task a message)"
    )
    assert "nothing held back" in costs.report(month, month, [], "dev.db", (1, 4, 4), 20)
    assert "List context" not in costs.report(month, month, [], "dev.db")


# ---------------------------------------------------------------------------
# The daily spend line
# ---------------------------------------------------------------------------
@pytest.fixture
def bot_log(monkeypatch):
    from core import discord_utils

    said = []

    async def log_simple(title, description=None):
        said.append((title, description))

    monkeypatch.setattr(discord_utils, "log_simple", log_simple)
    return said


def spend(amount_calls):
    """Log one message to Claude that made `amount_calls` requests of NZ$0.11 each."""
    async def scenario():
        row_id = await database.log_received("something long", "chat", 5, 100, user_id=1)
        await database.record_cost(row_id, ROUTER, ["pills"], [Call("extraction", HAIKU, 100_000, 2_000)] * amount_calls)

    asyncio.run(scenario())


def test_the_default_limit_is_fifty_cents_and_is_a_setting():
    from core import config

    assert config.DAILY_SPEND_LIMIT_NZD == 0.50, "the tests' own setting; the default is NZ$1.00"
    assert "DAILY_SPEND_LIMIT_NZD=1.00" in (config.BASE_DIR / ".env.example").read_text(encoding="utf-8")


def test_under_the_limit_nothing_is_said(db, bot_log):
    spend(4)  # NZ$0.44
    assert bot_log == []


def test_over_the_limit_bot_log_is_told_once_however_much_more_is_spent(db, bot_log):
    spend(4)
    spend(1)  # NZ$0.55: over
    assert bot_log == [("💰 Claude spend is over today's limit", "NZ$0.5500 (US$0.5500) so far today · the limit is NZ$0.50 (DAILY_SPEND_LIMIT_NZD in .env). Nothing is stopped; `dev cost` shows where it went.")]
    spend(3)
    spend(1)
    assert len(bot_log) == 1, "once a day, not once a message"


def test_it_is_not_said_again_after_a_restart_and_is_said_again_on_a_new_day(db, bot_log):
    spend(5)
    assert len(bot_log) == 1
    # A restart keeps nothing in memory: the day it was said is in the database
    conn = database.connect()
    try:
        assert conn.execute("SELECT COUNT(*), MIN(limit_usd) FROM spend_notices").fetchone() == (1, 0.5)
        assert costs.db_over_limit(conn, costs.day_start(datetime.now(TIMEZONE)), 0.50) is None, "said already today"
        conn.execute("UPDATE spend_notices SET day = '2020-01-01'")
        conn.commit()
        assert costs.db_over_limit(conn, datetime.now(TIMEZONE), 0.50) == pytest.approx(0.55), "another day: said once more"
    finally:
        conn.close()


def test_a_limit_of_nothing_switches_the_note_off_and_a_message_with_no_request_is_never_checked(db, bot_log, monkeypatch):
    from core import config

    monkeypatch.setattr(config, "DAILY_SPEND_LIMIT_NZD", 0.0)
    spend(9)
    assert bot_log == []
    conn = database.connect()
    try:
        assert costs.db_over_limit(conn, datetime.now(TIMEZONE), 0) is None and costs.db_over_limit(conn, datetime.now(TIMEZONE), -1) is None
    finally:
        conn.close()


def test_a_note_that_cannot_be_sent_never_fails_the_message(db, monkeypatch):
    from core import discord_utils

    async def broken(*_):
        raise RuntimeError("no #bot-log")

    monkeypatch.setattr(discord_utils, "log_simple", broken)
    spend(5)  # does not raise


def test_dev_cost_shows_today_against_the_limit():
    today = costs.add_up([Row(datetime.now(TIMEZONE), ROUTER, ("pills",), 1, 100, 10, 0, 0, 0.0317, 1.0)])
    lines = costs.report(today, today, [], "dev.db", limit=0.50).splitlines()
    assert lines[1].startswith("**Today** · NZ$0.0317") and "-# NZ$0.0317 of today's NZ$0.50 limit (6%)" in lines
    over = costs.add_up([Row(datetime.now(TIMEZONE), ROUTER, ("pills",), 1, 100, 10, 0, 0, 0.61, 1.0)])
    assert "-# ⚠️ over today's limit: NZ$0.6100 of NZ$0.50 (DAILY_SPEND_LIMIT_NZD)" in costs.report(over, over, [], "dev.db", limit=0.50)
    assert "limit" not in costs.report(today, today, [], "dev.db"), "no limit set: no line"
    empty = costs.add_up([])
    assert "-# NZ$0.0000 of today's NZ$0.50 limit (0%)" in costs.report(empty, empty, [], "dev.db", limit=0.50)
