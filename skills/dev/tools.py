import sqlite3

import discord

from core import devmode, reactions, scheduler
from core.context import Context
from core.errors import UserError
from core.protection import is_protected, protection
from core.scheduler import utc_now
from skills.archive import store as archive

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
        record = "the archive skill has no table (not loaded yet?)"

    lines = [
        f"🔎 **Message** `{target.id}` · {target.author.display_name} · sent {_stamp(target.created_at)}",
        f"Pinned: {'yes' if target.pinned else 'no'}",
        f"Protected from clean-up: {protection(target) or 'no'}",
        "Kept: not built yet",
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
async def jobs(ctx: Context) -> str:
    pending = await scheduler.all_pending()
    lines = [f"🗓️ **Pending jobs** ({len(pending)})"]
    lines += [
        f"`#{job.id}` {job.skill}/{job.kind} · due {_stamp(job.due_at)} ({_stamp(job.due_at, 't')})"
        for job in pending[:JOBS_SHOWN]
    ]
    if len(pending) > JOBS_SHOWN:
        lines.append(f"…and {len(pending) - JOBS_SHOWN} more")
    if not pending:
        lines.append("Nothing is booked.")
    lines.append(TAG)
    await ctx.reply("\n".join(lines))
    return f"{len(pending)} pending job(s)"


async def run(ctx: Context) -> str:
    if len(ctx.args) != 1:
        raise UserError(f"Usage: `dev run {'|'.join(devmode.TASK_NAMES)}`.")
    name = ctx.args[0].lower()
    await devmode.run_task(name)
    await ctx.confirm(f"▶️ Ran: {name}. The result is in #bot-log.")
    return f"ran {name}"


async def fire_next(ctx: Context) -> str:
    pending = await scheduler.all_pending()
    if not pending:
        raise UserError("There are no pending jobs to fire.")
    job = pending[0]
    if not await scheduler.reschedule_job(job.id, utc_now()):
        raise UserError(f"Job {job.id} ran or was cancelled before I could fire it.")
    await ctx.confirm(f"🔥 Fired job #{job.id}: {job.skill}/{job.kind}")
    return f"fired job {job.id} ({job.skill}/{job.kind}), which was due {job.due_at.isoformat(timespec='seconds')}"


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
    await ctx.confirm(f"🌱 Seeded {count} test message{'' if count == 1 else 's'}. `dev clean` removes them.")
    return f"seeded {count} test message(s)"


async def clean(ctx: Context) -> str:
    bot_id = ctx.channel.guild.me.id

    def is_test_data(message: discord.Message) -> bool:
        # Pinned or 📌-marked messages are never swept away, test data or not
        return message.author.id == bot_id and TAG in message.content and not is_protected(message)

    removed = await ctx.channel.purge(limit=CLEAN_LOOKBACK, check=is_test_data, reason="dev clean")
    await ctx.confirm(f"🧹 Removed {len(removed)} test message{'' if len(removed) == 1 else 's'}.")
    return f"removed {len(removed)} test message(s)"
