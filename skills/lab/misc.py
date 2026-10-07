import asyncio
import io
import time
from datetime import datetime, timedelta
from typing import Literal

import discord
from discord import app_commands

from core import scheduler
from core.config import ASSISTANT_NAME, BACKUP_TIME, now_nz
from core.discord_utils import split_message
from skills.lab import data
from skills.lab.common import (
    LabError,
    Run,
    SlashRun,
    check_owner,
    lab,
    lab_keyword,
    record,
    record_press,
    report_component_error,
)
from skills.lab.ratelimits import monitor

SLOW_EDIT = 1.5  # seconds; an edit slower than this was probably held back by a rate limit

# Each command below is one run_* function, reached two ways: a typed word
# (collected in KEYWORDS at the bottom) and a /lab slash command.

NOTIFY_KINDS = ["normal", "silent", "mention", "dm"]
NOTIFY_MODES = [*NOTIFY_KINDS, "all"]
NOTIFY_GAP = 5  # seconds between messages when sending all four
NOTIFY_MAX_DELAY = 3600  # seconds

# Notifications waiting to go out. Kept here so the tasks aren't garbage-collected;
# in memory only, so a restart forgets them.
_pending_notifications: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# lab notify
# ---------------------------------------------------------------------------
async def send_notification(run: Run, kind: str, label: str = "") -> None:
    """Send one test notification. `label` numbers it when it is part of a sequence."""
    if kind == "normal":
        await run.channel.send(
            f"🔔 **{label}Normal** message: notifies according to your channel settings."
        )
    elif kind == "silent":
        await run.channel.send(
            f"🔕 **{label}Silent** message: arrives without a sound or a push notification.",
            silent=True,
        )
    elif kind == "mention":
        await run.channel.send(
            f"📣 **{label}Mention**: {run.member.mention}, this one pings you directly.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )
    else:
        # DMs are short pointers back to a message in the server (see DECISIONS.md),
        # so the test posts something to point at
        marker = await run.channel.send(
            f"✉️ **{label}DM test**: a pointer to this message was sent to your DMs.", silent=True
        )
        try:
            await run.member.send(f"✉️ **{label}Test alert** from the lab: {marker.jump_url}")
        except discord.Forbidden:
            raise LabError(
                "I can't DM you. Allow direct messages from server members in this "
                "server's privacy settings."
            )


def describe_wait(seconds: int) -> str:
    return f"{seconds}s" if seconds < 120 else f"{seconds // 60}m {seconds % 60}s"


async def _send_later(run: Run, kinds: list[str], delay: int) -> None:
    """Wait, then send the notifications a few seconds apart. Runs in the background."""
    label = f"notify: {', '.join(kinds)} after {describe_wait(delay)}"
    sent, problems = [], []
    try:
        await asyncio.sleep(delay)
        for position, kind in enumerate(kinds, start=1):
            if position > 1:
                await asyncio.sleep(NOTIFY_GAP)
            numbering = f"{position}/{len(kinds)} " if len(kinds) > 1 else ""
            try:
                await send_notification(run, kind, numbering)
                sent.append(kind)
            except (LabError, discord.HTTPException) as error:
                # One failing (DMs closed, say) shouldn't stop the rest
                problems.append(f"{kind}: {error}")
    except Exception as error:
        problems.append(repr(error))

    summary = f"sent: {', '.join(sent) or 'none'}"
    if problems:
        summary += f"; failed: {'; '.join(problems)}"
    await record(label, summary, channel_id=getattr(run.channel, "id", None), user_id=run.user_id)


async def run_notify(run: Run, mode: str, delay: int = 0) -> None:
    await run.start()
    kinds = NOTIFY_KINDS if mode == "all" else [mode]

    if mode != "all" and delay == 0:
        await send_notification(run, mode)
        run.note(f"sent a {mode} notification")
        await run.done(f"Sent ({mode}).")
        return

    # A sequence or a delay: answer now, send in the background
    task = asyncio.create_task(_send_later(run, kinds, delay), name="lab notify")
    _pending_notifications.add(task)
    task.add_done_callback(_pending_notifications.discard)

    what = f"all four, {NOTIFY_GAP} seconds apart" if mode == "all" else f"a {mode} notification"
    when = f"in {describe_wait(delay)}" if delay else "now"
    run.note(f"scheduled {what} {when}")
    await run.done(f"⏱️ Sending {what}, starting {when}.")


@lab.command(name="notify", description="Send a test notification, or all four, now or after a delay")
@app_commands.describe(
    mode="How the message should be delivered; 'all' sends each kind in turn",
    delay="Seconds to wait first, so you can lock your phone",
)
async def notify(
    interaction: discord.Interaction,
    mode: Literal["normal", "silent", "mention", "dm", "all"],
    delay: app_commands.Range[int, 0, NOTIFY_MAX_DELAY] = 0,
):
    await run_notify(SlashRun(interaction), mode, delay)


def parse_notify(args) -> tuple[str, int]:
    """`<mode> [delay] [seconds]`: "all delay 90" and "all 90" both work."""
    mode = args.choice(NOTIFY_MODES)
    return mode, args.delay(NOTIFY_MAX_DELAY)


# ---------------------------------------------------------------------------
# /lab time
# ---------------------------------------------------------------------------
TIMESTAMP_STYLES = [
    ("t", "short time"),
    ("T", "long time"),
    ("d", "short date"),
    ("D", "long date"),
    ("f", "short date and time"),
    ("F", "long date and time"),
    ("R", "relative"),
]


def build_time_demo(now: datetime) -> str:
    """Every dynamic timestamp style. Discord shows each in the reader's own timezone."""
    unix = int(now.timestamp())
    soon = int((now + timedelta(minutes=90)).timestamp())
    backup = int(scheduler.next_run(BACKUP_TIME, now).timestamp())

    lines = ["🕒 **Dynamic timestamps** (shown in each reader's own timezone)"]
    for style, name in TIMESTAMP_STYLES:
        lines.append(f"`<t:{unix}:{style}>` {name}: <t:{unix}:{style}>")
    lines.append("")
    lines.append(f"In 90 minutes: <t:{soon}:t> (<t:{soon}:R>)")
    lines.append(f"Next backup: <t:{backup}:F> (<t:{backup}:R>)")
    lines.append("-# Relative times count down by themselves, with no edits from the bot.")
    return "\n".join(lines)


async def run_time(run: Run) -> None:
    await run.start()
    await run.channel.send(build_time_demo(now_nz()))
    run.note("posted the timestamp styles")
    await run.done("Timestamps posted.")


@lab.command(name="time", description="Show every dynamic timestamp style")
async def time_demo(interaction: discord.Interaction):
    await run_time(SlashRun(interaction))


# ---------------------------------------------------------------------------
# lab thread
# ---------------------------------------------------------------------------
async def run_thread(run: Run) -> None:
    await run.start()
    if not isinstance(run.channel, discord.TextChannel):
        raise LabError("Threads can only be started from a normal text channel.")

    starter = await run.channel.send("🧵 **Thread test**: replies go in the thread below.")
    new_thread = await starter.create_thread(
        name=f"Lab thread {now_nz():%d %b %H:%M}", auto_archive_duration=60
    )
    await new_thread.send("👋 First message inside the thread. It archives after an hour of quiet.")

    run.note(f"started thread {new_thread.name}")
    await run.done(f"Started {new_thread.mention}.")


@lab.command(name="thread", description="Post a message and start a thread on it")
async def thread(interaction: discord.Interaction):
    await run_thread(SlashRun(interaction))


# ---------------------------------------------------------------------------
# /lab poll
# ---------------------------------------------------------------------------
def build_poll(multiple: bool) -> discord.Poll:
    poll = discord.Poll(
        question=f"Which Discord feature should {ASSISTANT_NAME} lean on most?",
        duration=timedelta(hours=1),
        multiple=multiple,
    )
    poll.add_answer(text="Buttons", emoji="🔘")
    poll.add_answer(text="Reactions", emoji="📌")
    poll.add_answer(text="Slash commands", emoji="⌨️")
    poll.add_answer(text="Plain chat", emoji="💬")
    return poll


async def run_poll(run: Run, multiple: bool) -> None:
    await run.start()
    await run.channel.send(poll=build_poll(multiple))
    run.note(f"posted a poll (multiple answers: {'yes' if multiple else 'no'})")
    await run.done("Poll posted.")


@lab.command(name="poll", description="Post a native poll that runs for an hour")
@app_commands.describe(multiple="Allow more than one answer")
async def poll(interaction: discord.Interaction, multiple: bool = False):
    await run_poll(SlashRun(interaction), multiple)


# ---------------------------------------------------------------------------
# lab file
# ---------------------------------------------------------------------------
async def run_file(run: Run, days: int) -> None:
    await run.start()
    stats = await data.daily_stats(days)
    # The BOM makes Excel read the file as UTF-8
    content = data.build_csv(stats).encode("utf-8-sig")
    attachment = discord.File(io.BytesIO(content), filename=f"hive-stats-{now_nz():%Y-%m-%d}.csv")
    await run.channel.send(f"📎 Daily stats for the last {days} days.", file=attachment)
    run.note(f"sent {days} days of stats as CSV ({len(content)} bytes)")
    await run.done("File posted.")


@lab.command(name="file", description="Send daily stats as a CSV file")
@app_commands.describe(days="How many days to include, ending today")
async def file(interaction: discord.Interaction, days: app_commands.Range[int, 1, 365] = 30):
    await run_file(SlashRun(interaction), days)


# ---------------------------------------------------------------------------
# /lab format
# ---------------------------------------------------------------------------
ESC = "\u001b"


def format_samples() -> list[str]:
    """One message per formatting feature."""
    markdown = "\n".join(
        [
            "# Heading 1",
            "## Heading 2",
            "### Heading 3",
            "**Bold**, *italic*, __underline__, ~~strikethrough~~ and `inline code`.",
            "> A block quote",
            "- A bullet",
            "  - A nested bullet",
            "1. A numbered item",
            "[A masked link](https://discord.com)",
            "-# Subtext: small grey text for footnotes",
        ]
    )
    spoilers = "\n".join(
        [
            "🙈 **Spoilers**: tap to reveal → ||the butler did it||",
            "They work on part of a line, or on ||whole sentences at once||.",
            "```python",
            "def greet(name):",
            '    return f"Kia ora, {name}"',
            "```",
        ]
    )
    ansi = "\n".join(
        [
            "🎨 **ANSI colours** (desktop only; phones show plain text)",
            "```ansi",
            f"{ESC}[1;31mRed bold{ESC}[0m  {ESC}[32mGreen{ESC}[0m  {ESC}[33mYellow{ESC}[0m  {ESC}[34mBlue{ESC}[0m",
            f"{ESC}[35mMagenta{ESC}[0m  {ESC}[36mCyan{ESC}[0m  {ESC}[4mUnderlined{ESC}[0m",
            f"{ESC}[1;37;41m ERROR {ESC}[0m something failed",
            f"{ESC}[1;30;42m  OK   {ESC}[0m all good",
            "```",
        ]
    )
    return [markdown, spoilers, ansi]


def long_text() -> str:
    """About 4,500 characters, to show a reply being split across messages."""
    lines = ["📜 **Long message splitting** (one reply, cut at line breaks)"]
    number = 1
    while sum(len(line) + 1 for line in lines) < 4500:
        lines.append(
            f"{number:03d}. This line pads the message out so it has to be split across several."
        )
        number += 1
    return "\n".join(lines)


async def run_format(run: Run) -> None:
    await run.start()
    for sample in format_samples():
        await run.channel.send(sample)
    chunks = split_message(long_text())
    for chunk in chunks:
        await run.channel.send(chunk)

    run.note(f"posted 3 formatting samples and a long text in {len(chunks)} parts")
    await run.done("Formatting samples posted.")


@lab.command(name="format", description="Markdown, spoilers, ANSI colours and long message splitting")
async def format_demo(interaction: discord.Interaction):
    await run_format(SlashRun(interaction))


# ---------------------------------------------------------------------------
# /lab layout (components v2)
# ---------------------------------------------------------------------------
def supports_layout() -> bool:
    return all(
        hasattr(discord.ui, name)
        for name in ("LayoutView", "Container", "Section", "TextDisplay", "Thumbnail", "Separator")
    )


def build_layout(avatar_url: str) -> "discord.ui.LayoutView":
    ui = discord.ui

    class LabLayout(ui.LayoutView):
        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            return await check_owner(interaction)

        async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
            await report_component_error(interaction, error, "layout")

    async def pressed(interaction: discord.Interaction) -> None:
        reply = "🧩 Pressed a button inside a components v2 layout."
        await interaction.response.send_message(reply, ephemeral=True)
        await record_press(interaction, "layout button", reply)

    section_button = ui.Button(label="Press me", style=discord.ButtonStyle.primary)
    section_button.callback = pressed
    row_button = ui.Button(label="Me too", style=discord.ButtonStyle.secondary)
    row_button.callback = pressed
    link_button = ui.Button(label="discord.py docs", url="https://discordpy.readthedocs.io/")

    container = ui.Container(
        ui.TextDisplay("## 🧩 Components v2\nText, images and buttons laid out in one message."),
        ui.Separator(),
        ui.Section(
            "**Section with a thumbnail**\nText on the left, a picture on the right.",
            accessory=ui.Thumbnail(avatar_url),
        ),
        ui.Section(
            "**Section with a button**\nThe button sits beside the text it belongs to.",
            accessory=section_button,
        ),
        ui.Separator(),
        ui.TextDisplay("-# A row of buttons can go anywhere in the layout:"),
        ui.ActionRow(row_button, link_button),
        accent_colour=discord.Colour.blurple(),
    )

    view = LabLayout(timeout=300)
    view.add_item(container)
    return view


async def run_layout(run: Run) -> None:
    await run.start()
    if not supports_layout():
        raise LabError(
            f"Components v2 needs discord.py 2.6 or newer (installed: {discord.__version__})."
        )
    avatar_url = run.client.user.display_avatar.url
    # A components v2 message can't also have ordinary text or embeds
    await run.channel.send(view=build_layout(avatar_url))
    run.note("posted a components v2 layout")
    await run.done("Layout posted.")


@lab.command(name="layout", description="Components v2: a message built from containers and sections")
async def layout(interaction: discord.Interaction):
    await run_layout(SlashRun(interaction))


# ---------------------------------------------------------------------------
# /lab countdown
# ---------------------------------------------------------------------------
def render_countdown(left: int, total: int) -> str:
    filled = round(10 * (total - left) / total)
    return f"⏳ **{left}s** left  `{'█' * filled}{'░' * (10 - filled)}`"


def countdown_summary(total: int, edits: int, hits: int, slow: int, slowest: float) -> str:
    return (
        f"✅ **Countdown finished** ({total}s)\n"
        f"Edits: {edits} · Rate-limit warnings: {hits} · "
        f"Slow edits (over {SLOW_EDIT}s): {slow} · Slowest edit: {slowest:.2f}s"
    )


async def run_countdown(run: Run, seconds: int, step: int) -> None:
    await run.start()
    message = await run.channel.send(render_countdown(seconds, seconds))
    await run.done("Countdown started.")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    hits_before = monitor.count
    edits = slow = 0
    slowest = 0.0

    while (remaining := deadline - loop.time()) > 0:
        await asyncio.sleep(min(step, remaining))
        left = max(0, round(deadline - loop.time()))
        if left == 0:
            break
        started = time.perf_counter()
        await message.edit(content=render_countdown(left, seconds))
        took = time.perf_counter() - started
        edits += 1
        slowest = max(slowest, took)
        if took > SLOW_EDIT:
            slow += 1

    summary = countdown_summary(seconds, edits, monitor.count - hits_before, slow, slowest)
    await message.edit(content=summary)
    run.note(summary)


@lab.command(name="countdown", description="A message that counts down by editing itself")
@app_commands.describe(seconds="How long to count down for", step="Seconds between edits")
async def countdown(
    interaction: discord.Interaction,
    seconds: app_commands.Range[int, 5, 120] = 30,
    step: app_commands.Range[int, 1, 30] = 5,
):
    await run_countdown(SlashRun(interaction), seconds, step)


# ---------------------------------------------------------------------------
# The typed forms
# ---------------------------------------------------------------------------
KEYWORDS = [
    lab_keyword(
        "lab notify",
        "send a test notification (normal, silent, @mention, DM, or all four in turn), "
        "now or after a delay in seconds",
        run_notify,
        usage="<normal|silent|mention|dm|all> [delay <seconds>]",
        parse=parse_notify,
        examples=["lab notify silent", "lab notify all delay 90"],
    ),
    lab_keyword("lab time", "show every dynamic timestamp style", run_time),
    lab_keyword("lab thread", "post a message and start a thread on it", run_thread),
    lab_keyword(
        "lab poll",
        "post a native poll that runs for an hour",
        run_poll,
        usage="[multiple]",
        parse=lambda args: (args.flag("multiple"),),
        examples=["lab poll", "lab poll multiple"],
    ),
    lab_keyword(
        "lab file",
        "send daily stats as a CSV file",
        run_file,
        usage="[days]",
        parse=lambda args: (args.number("days", 30, 1, 365),),
        examples=["lab file", "lab file 7"],
    ),
    lab_keyword("lab format", "markdown, spoilers, ANSI colours and long message splitting", run_format),
    lab_keyword("lab layout", "components v2: a message built from containers and sections", run_layout),
    lab_keyword(
        "lab countdown",
        "a message that counts down by editing itself, reporting rate limits",
        run_countdown,
        usage="[seconds] [step]",
        parse=lambda args: (args.number("seconds", 30, 5, 120), args.number("step", 5, 1, 30)),
        examples=["lab countdown", "lab countdown 20 1"],
    ),
]
