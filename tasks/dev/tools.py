import asyncio
import sqlite3

import discord

from core import about, backup, clock, confirmations, database, day, devmode, instance_lock, lifecycle, migrations
from core import actions, costs, reactions, scheduler, timeinput, trace, users
from core.clock import real_now
from core.config import DAILY_SPEND_LIMIT, DB_PATH, DEV_DATABASE, TIMEZONE
from core.durations import format_duration
from core.context import Context
from core.errors import UserError
from core.protection import is_kept, is_protected, protection
from core.scheduler import utc_now
from tasks import registry
from tasks.archive import store as archive

# ---------------------------------------------------------------------------
# Dev tools: looking inside a message, the scheduler, and sample messages to
# practise on. What they post carries TAG, so `dev clean` can find it again.
# ---------------------------------------------------------------------------
TAG = "-# 🧪 dev test data"
MAX_SEED = 20
CLEAN_LOOKBACK = 200  # how many recent messages `dev clean` looks through
JOBS_SHOWN = 20

SAMPLES = [
    "Buy oat milk and coffee beans",
    "Idea: a weekly review card every Sunday evening",
    "Dentist said to book a check-up for March",
    "https://example.com/an-article-to-read-later",
    "Remember to renew the car registration",
    "Gym: 3 x 8 squats at 60 kg felt easy",
    "Call the plumber about the kitchen tap",
    "Book recommendation from Sam: The Dispossessed",
]


def _stamp(moment, style: str = "R") -> str:
    return f"<t:{int(moment.timestamp())}:{style}>"


# ---------------------------------------------------------------------------
# dev inspect (as a reply)
# ---------------------------------------------------------------------------
def _ran_a_command(conn: sqlite3.Connection, message_id: int) -> bool:
    """Whether that message was a typed word or a reply action (from message_log)."""
    row = conn.execute(
        "SELECT 1 FROM message_log WHERE discord_message_id = ? AND kind IN ('command', 'reply_action') LIMIT 1",
        (message_id,),
    ).fetchone()
    return row is not None


async def inspect(ctx: Context, target: discord.Message) -> str:
    try:
        # The copy that came with the reply can be out of date: reactions change
        target = await target.channel.fetch_message(target.id)
    except discord.HTTPException:
        pass

    on_message = ", ".join(
        f"{reaction.emoji} ×{reaction.count}{' (incl. mine)' if reaction.me else ''}"
        for reaction in target.reactions
    )
    applied = await ctx.db.run(reactions.db_applied, [target.id])
    try:
        record = await archive.describe_record(target.id)
    except sqlite3.OperationalError:
        record = "the archive task has no table (not loaded yet?)"

    message_class = lifecycle.classify(
        protected=is_protected(target),
        declared=await registry.declared_class(target.id),
        transient=lifecycle.is_transient(target.id),
        command=await ctx.db.run(_ran_a_command, target.id),
    )

    lines = [
        f"🔎 **Message** `{target.id}` · {target.author.display_name} · sent {_stamp(target.created_at)}",
        f"Lifecycle: {lifecycle.describe(message_class)}",
        f"Pinned: {'yes' if target.pinned else 'no'}",
        f"Protected from clean-up: {protection(target) or 'no'}",
        f"Kept: {'yes' if is_kept(applied) else 'no'}",
        f"Reactions on it: {on_message or 'none'}",
        f"Reactions applied: {', '.join(sorted(key[1] for key in applied)) or 'none'}",
        f"Archive record: {record or 'none'}",
        TAG,
    ]
    await ctx.reply("\n".join(lines))
    return f"inspected {target.id}: " + "; ".join(lines[1:-1])


# ---------------------------------------------------------------------------
# dev jobs, dev run, dev fire next
# ---------------------------------------------------------------------------
_ENDED = {scheduler.DONE: "✅", scheduler.FAILED: "❌ failed", scheduler.SKIPPED: "⚠️ skipped", scheduler.MISSED: "⏭️ set aside"}


async def jobs(ctx: Context) -> str:
    """What is booked next, and how the last run of each kind of job ended:
    the engine's own run log (core/scheduler.py)."""
    pending = await scheduler.all_pending()
    lines = [f"🗓️ **Pending jobs** ({len(pending)})"]
    lines += [
        f"`#{job.id}` {job.task}/{job.kind} · due {_stamp(job.due_at)} ({_stamp(job.due_at, 't')})" + (f" · for {job.local_at.replace('T', ' ')}" if job.local_at else "")
        for job in pending[:JOBS_SHOWN]
    ]
    if len(pending) > JOBS_SHOWN:
        lines.append(f"…and {len(pending) - JOBS_SHOWN} more")
    if not pending:
        lines.append("Nothing is booked.")
    last = await scheduler.last_runs()
    if last:
        lines.append("**Last run of each**")
        for task, kind, status, due_at, late_by, note in last[:JOBS_SHOWN]:
            late = f" · {format_duration(late_by)} late" if late_by and late_by > scheduler.LATE_AFTER_SECONDS else ""
            lines.append(f"{_ENDED.get(status, status)} {task}/{kind} · {_stamp(scheduler.from_db(due_at))}{late}" + (f" · {note}" if note else ""))
    lines.append(TAG)
    await ctx.reply("\n".join(lines)[:1990])
    return f"{len(pending)} pending job(s)"


def handler_for(asked: str) -> tuple[str, str]:
    """The handler a word of `dev run` means: its name ("core.nightly_backup"),
    its kind, a word of its kind ("backup") or its name in words. One that
    fits none, or more than one, is said with the names there are."""
    wanted = asked.strip().lower()
    known = scheduler.handlers()
    fits = [
        (task, kind) for task, kind in known
        if wanted in (scheduler.handler_name(task, kind), kind, scheduler.label(task, kind).lower().replace(" ", "-")) or wanted in kind.split("_")
    ]
    if len(fits) == 1:
        return fits[0]
    names = ", ".join(scheduler.handler_name(task, kind) for task, kind in (fits or known))
    raise UserError(f"“{asked}” is more than one handler: {names}." if fits else f"I don't know a handler called “{asked}”. Try: {names}.")


async def run(ctx: Context) -> str:
    if len(ctx.args) != 1:
        raise UserError("Usage: `dev run <handler>`, for example `dev run backup`. `dev jobs` shows what there is.")
    task, kind = handler_for(ctx.args[0])
    await scheduler.run_now(task, kind)
    name = scheduler.handler_name(task, kind)
    await ctx.confirm(f"▶️ Ran: {name}. The result is in #bot-log.")
    return f"ran {name}"


async def fire_next(ctx: Context) -> str:
    pending = await scheduler.all_pending()
    if not pending:
        raise UserError("There are no pending jobs to fire.")
    job = pending[0]
    if not await scheduler.fire(job.id):
        raise UserError(f"Job {job.id} ran or was cancelled before I could fire it.")
    await ctx.confirm(f"🔥 Fired job #{job.id}: {job.task}/{job.kind}")
    return f"fired job {job.id} ({job.task}/{job.kind}), which was due {job.due_at.isoformat(timespec='seconds')}"


# ---------------------------------------------------------------------------
# dev cost
# ---------------------------------------------------------------------------
async def cost(ctx: Context) -> str:
    """What the messages in this database cost: today, this month, the average
    per message and the most expensive task. By the real clock: costs are real
    whatever the dev clock says."""
    now = real_now()
    since = costs.month_start(now).isoformat()
    rows = await ctx.db.run(costs.db_rows, since)
    purposes = await ctx.db.run(costs.db_purposes, since)
    today, month = costs.split(rows, now)
    state = await ctx.db.run(costs.db_state_sent, since)
    await ctx.reply(costs.report(today, month, purposes, database.DB_PATH.name, state, actions.STATE_LINES, DAILY_SPEND_LIMIT))
    return f"today {costs.money(today.cost)} over {today.messages} message(s); this month {costs.money(month.cost)} over {month.messages}"


# ---------------------------------------------------------------------------
# dev why
# ---------------------------------------------------------------------------
WHY_USAGE = "dev why [<how many>]"
NO_LOG = (
    "🔎 Nothing is logged for that message: it is from before this database was started "
    f"(`{'dev.db' if DEV_DATABASE else 'assistant.db'}` only knows what came after)."
)
WHY_MOST = 10
# What counts as "a message from me": what I typed, and the buttons I pressed
WHY_KINDS = (*database.OWN_MESSAGE_KINDS, "card")


def why_count(args: list[str]) -> int:
    """How many messages `dev why` shows: one, or the number given (up to WHY_MOST)."""
    if not args:
        return 1
    if len(args) != 1 or not args[0].isdigit() or not 1 <= int(args[0]) <= WHY_MOST:
        raise UserError(f"Usage: `{WHY_USAGE}`, from 1 to {WHY_MOST}.")
    return int(args[0])


async def why(ctx: Context) -> str:
    """The last messages from the user, each as one block that can be copied
    whole: what was said, the route and why, what the router and extraction
    returned, what the code applied, the card before and after, the cost."""
    count = why_count(ctx.args)
    upto = None
    if ctx.reply_target_id is not None:
        # As a reply: the messages up to and including the one replied to (for one
        # of the bot's messages, the message of mine it answered)
        target = await ctx.fetch_reply_target()
        sent_at = getattr(target, "created_at", None)
        upto = await ctx.db.run(trace.db_anchor, ctx.user.id, WHY_KINDS, ctx.reply_target_id, sent_at)
        if upto is None:
            # Not a failure: said in a line. (A failed word only gets ⚠️, with its reason in #bot-log)
            await ctx.reply(NO_LOG)
            return "nothing is logged for the message replied to"
    rows = await ctx.db.run(trace.db_recent, ctx.user.id, count, WHY_KINDS, "dev why", upto)
    if not rows:
        await ctx.reply("🔎 Nothing is logged from you yet in this database.")
        return "nothing is logged yet"
    for row in rows:
        # As it is: a trace names actions and fields, which is what it is for
        await ctx.reply(trace.block(row), verbatim=True)
    return f"showed the trace of message(s) {', '.join('#' + str(row['id']) for row in rows)}"


# ---------------------------------------------------------------------------
# dev reset-db
# ---------------------------------------------------------------------------
def _start_empty(task_migrations: dict[str, list]) -> None:
    """Delete the dev database and build an empty one. Blocking."""
    database.wipe_dev()  # refuses anything but the dev database
    migrations.migrate(task_migrations)
    users.clear_user_cache()
    users.ensure_owner()


async def reset_db(ctx: Context) -> str:
    if not DEV_DATABASE:
        raise UserError(
            "`dev reset-db` only works on the dev database (`python main.py --dev`). "
            "The live database is never wiped."
        )

    async def wipe() -> str:
        await asyncio.to_thread(_start_empty, registry.task_migrations())
        clock.reset()
        # Every schedule and every booked run went with the rest: the defaults are made
        # again and each is booked for the time it now is
        await scheduler.clock_went_back()
        return f"🧹 `{DB_PATH.name}` wiped, clock back at the real time. Restart the bot if anything looks stale."

    await confirmations.ask(
        ctx.channel,
        ctx.user,
        f"Wipe the dev database (`{DB_PATH.name}`)? Every record in it goes, and the clock returns to the real time.",
        wipe,
    )
    ctx.shown("confirmation question")
    return "asked before wiping the dev database"


# ---------------------------------------------------------------------------
# dev status
# ---------------------------------------------------------------------------
def _when(moment) -> str:
    local = moment.astimezone(TIMEZONE)
    return f"{local:%a} {local.day} {local:%b}, {timeinput.format_time(local.time())}"


def status_lines(dev: bool, database_name: str, up: float, commit: str, ahead, now, pending: list) -> list[str]:
    """What is running, in lines: which bot and database, for how long, at which
    commit, what the clock reads, and when each kind of job runs next."""
    lines = [
        f"{'🧪 **Dev** bot' if dev else '🟢 **Live** bot'} · database `{database_name}`",
        f"Up {format_duration(up)} · code at {commit} when it started",
        f"Clock: {_when(now)} " + (f"(dev clock, {format_duration(ahead.total_seconds())} ahead)" if ahead else "(the real time)"),
    ]
    first: dict[str, object] = {}
    for job in pending:  # soonest first
        first.setdefault(f"{job.task}/{job.kind}", job)
    lines += [f"Next {name}: {_when(job.due_at)} (`#{job.id}`)" for name, job in first.items()] or ["No job is booked."]
    return lines


async def status(ctx: Context) -> str:
    """What is running, and how many bots: the lock's answer, checked against the processes."""
    text = await asyncio.to_thread(instance_lock.status)
    up = (real_now() - about.STARTED).total_seconds()
    lines = status_lines(DEV_DATABASE, DB_PATH.name, up, about.COMMIT, clock.offset(), clock.now(), await scheduler.all_pending())
    await ctx.reply("🩺 **Status**\n" + "\n".join(lines) + f"\n**Bot instances**\n{text}\n{TAG}")
    return text


# ---------------------------------------------------------------------------
# dev seed <n>, dev clean
# ---------------------------------------------------------------------------
async def seed(ctx: Context) -> str:
    try:
        count = int(ctx.args[0]) if len(ctx.args) == 1 else 0
    except ValueError:
        count = 0
    if not 1 <= count <= MAX_SEED:
        raise UserError(f"Usage: `dev seed <n>`, with n from 1 to {MAX_SEED}.")
    for number in range(count):
        sample = SAMPLES[number % len(SAMPLES)]
        await ctx.channel.send(f"{sample}\n{TAG}", silent=True)
    # Instructions are Kept, not a passing confirmation; tagged, so `dev clean` takes them too
    await ctx.reply(f"🌱 Seeded {count} test message{'' if count == 1 else 's'}. `dev clean` removes them.\n{TAG}")
    return f"seeded {count} test message(s)"


async def clean(ctx: Context) -> str:
    bot_id = ctx.channel.guild.me.id

    def is_test_data(message: discord.Message) -> bool:
        # Pinned or 📌-marked messages are never swept away, test data or not
        return message.author.id == bot_id and TAG in message.content and not is_protected(message)

    removed = await ctx.channel.purge(limit=CLEAN_LOOKBACK, check=is_test_data, reason="dev clean")
    await ctx.confirm(f"🧹 Removed {len(removed)} test message{'' if len(removed) == 1 else 's'}.")
    return f"removed {len(removed)} test message(s)"
