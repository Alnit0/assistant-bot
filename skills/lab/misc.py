import asyncio
import io
import time
from datetime import datetime, timedelta
from typing import Literal

import discord
from discord import app_commands

from core import scheduler
from core.config import BACKUP_TIME, now_nz
from core.discord_utils import split_message
from skills.lab import data
from skills.lab.common import (
    LabError,
    check_owner,
    lab,
    note,
    record_press,
    target_channel,
)
from skills.lab.ratelimits import monitor

SLOW_EDIT = 1.5  # seconds; an edit slower than this was probably held back by a rate limit


# ---------------------------------------------------------------------------
# /lab notify
# ---------------------------------------------------------------------------
@lab.command(name="notify", description="Send a test notification: normal, silent, @mention or DM")
@app_commands.describe(mode="How the message should be delivered")
async def notify(
    interaction: discord.Interaction, mode: Literal["normal", "silent", "mention", "dm"]
):
    await interaction.response.defer(ephemeral=True)
    channel = target_channel(interaction)

    if mode == "normal":
        await channel.send("🔔 **Normal** message: notifies according to your channel settings.")
    elif mode == "silent":
        await channel.send(
            "🔕 **Silent** message: arrives without a sound or a push notification.", silent=True
        )
    elif mode == "mention":
        await channel.send(
            f"📣 **Mention**: {interaction.user.mention}, this one pings you directly.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )
    else:
        try:
            await interaction.user.send("✉️ **Direct message** from the lab.")
        except discord.Forbidden:
            raise LabError(
                "I can't DM you. Allow direct messages from server members in this "
                "server's privacy settings."
            )

    note(interaction, f"sent a {mode} notification")
    await interaction.followup.send(f"Sent ({mode}).", ephemeral=True)


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


@lab.command(name="time", description="Show every dynamic timestamp style")
async def time_demo(interaction: discord.Interaction):
    await interaction.response.send_message(build_time_demo(now_nz()))
    note(interaction, "posted the timestamp styles")


# ---------------------------------------------------------------------------
# /lab thread
# ---------------------------------------------------------------------------
@lab.command(name="thread", description="Post a message and start a thread on it")
async def thread(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    channel = target_channel(interaction)
    if not isinstance(channel, discord.TextChannel):
        raise LabError("Threads can only be started from a normal text channel.")

    starter = await channel.send("🧵 **Thread test**: replies go in the thread below.")
    new_thread = await starter.create_thread(
        name=f"Lab thread {now_nz():%d %b %H:%M}", auto_archive_duration=60
    )
    await new_thread.send("👋 First message inside the thread. It archives after an hour of quiet.")

    note(interaction, f"started thread {new_thread.name}")
    await interaction.followup.send(f"Started {new_thread.mention}.", ephemeral=True)


# ---------------------------------------------------------------------------
# /lab poll
# ---------------------------------------------------------------------------
def build_poll(multiple: bool) -> discord.Poll:
    poll = discord.Poll(
        question="Which Discord feature should Hive lean on most?",
        duration=timedelta(hours=1),
        multiple=multiple,
    )
    poll.add_answer(text="Buttons", emoji="🔘")
    poll.add_answer(text="Reactions", emoji="📌")
    poll.add_answer(text="Slash commands", emoji="⌨️")
    poll.add_answer(text="Plain chat", emoji="💬")
    return poll


@lab.command(name="poll", description="Post a native poll that runs for an hour")
@app_commands.describe(multiple="Allow more than one answer")
async def poll(interaction: discord.Interaction, multiple: bool = False):
    await interaction.response.defer(ephemeral=True)
    await target_channel(interaction).send(poll=build_poll(multiple))
    note(interaction, f"posted a poll (multiple answers: {'yes' if multiple else 'no'})")
    await interaction.followup.send("Poll posted.", ephemeral=True)


# ---------------------------------------------------------------------------
# /lab file
# ---------------------------------------------------------------------------
@lab.command(name="file", description="Send daily stats as a CSV file")
@app_commands.describe(days="How many days to include, ending today")
async def file(interaction: discord.Interaction, days: app_commands.Range[int, 1, 365] = 30):
    await interaction.response.defer()
    stats = await data.daily_stats(days)
    # The BOM makes Excel read the file as UTF-8
    content = data.build_csv(stats).encode("utf-8-sig")
    attachment = discord.File(io.BytesIO(content), filename=f"hive-stats-{now_nz():%Y-%m-%d}.csv")
    await interaction.followup.send(f"📎 Daily stats for the last {days} days.", file=attachment)
    note(interaction, f"sent {days} days of stats as CSV ({len(content)} bytes)")


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


@lab.command(name="format", description="Markdown, spoilers, ANSI colours and long message splitting")
async def format_demo(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    channel = target_channel(interaction)

    for sample in format_samples():
        await channel.send(sample)
    chunks = split_message(long_text())
    for chunk in chunks:
        await channel.send(chunk)

    note(interaction, f"posted 3 formatting samples and a long text in {len(chunks)} parts")
    await interaction.followup.send("Formatting samples posted.", ephemeral=True)


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


@lab.command(name="layout", description="Components v2: a message built from containers and sections")
async def layout(interaction: discord.Interaction):
    if not supports_layout():
        await interaction.response.send_message(
            f"Components v2 needs discord.py 2.6 or newer (installed: {discord.__version__}).",
            ephemeral=True,
        )
        note(interaction, "components v2 not supported by this discord.py")
        return

    avatar_url = interaction.client.user.display_avatar.url
    # A components v2 message can't also have ordinary text or embeds
    await interaction.response.send_message(view=build_layout(avatar_url))
    note(interaction, "posted a components v2 layout")


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


@lab.command(name="countdown", description="A message that counts down by editing itself")
@app_commands.describe(seconds="How long to count down for", step="Seconds between edits")
async def countdown(
    interaction: discord.Interaction,
    seconds: app_commands.Range[int, 5, 120] = 30,
    step: app_commands.Range[int, 1, 30] = 5,
):
    await interaction.response.defer(ephemeral=True)
    message = await target_channel(interaction).send(render_countdown(seconds, seconds))
    await interaction.followup.send("Countdown started.", ephemeral=True)

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
    note(interaction, summary)
