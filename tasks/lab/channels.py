import asyncio
import logging
from dataclasses import dataclass

import discord

from core import llm
from core.config import CHANNELS
from core.context import Context
from tasks import registry
from tasks.lab.common import LabError, Run, lab_keyword, record

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# lab channels: are notifications from each channel noticed, and how fast?
#
# After an optional delay, posts one test message in each channel below, each
# in a different style, and waits for the user to reply in that channel. Then
# posts a results card with the response times. Typed only (no slash command).
# ---------------------------------------------------------------------------
# Channel name (from config.CHANNELS) and the style of message it gets
PLAN = [
    ("reminders", "normal"),
    ("gym", "mention"),
    ("admin", "silent"),
    ("inbox", "link"),
]
STYLE_NAMES = {
    "normal": "normal",
    "mention": "@mention",
    "silent": "silent",
    "link": "cross-channel link",
}
GAP = 5  # seconds between channels
REPLY_TIMEOUT = 600  # seconds to wait for replies after the last message goes out
MAX_DELAY = 3600

# The test in progress, if any. In memory only: a restart forgets it.
_runner: asyncio.Task | None = None


@dataclass
class Probe:
    name: str  # our name for the channel
    style: str
    channel: discord.abc.Messageable | None = None
    problem: str | None = None  # why it couldn't be tested
    message: discord.Message | None = None
    sent_at: float | None = None  # event loop time
    replied_after: float | None = None  # seconds


def format_seconds(seconds: float) -> str:
    whole = round(seconds)
    return f"{whole}s" if whole < 60 else f"{whole // 60}m {whole % 60:02d}s"


def build_probes(client: discord.Client) -> list[Probe]:
    probes = []
    for name, style in PLAN:
        probe = Probe(name, style)
        channel_id = CHANNELS.get(name)
        if channel_id is None:
            probe.problem = "not set in .env"
        else:
            probe.channel = client.get_channel(channel_id)
            if probe.channel is None:
                probe.problem = "the bot can't see that channel"
        probes.append(probe)
    return probes


def test_text(probe: Probe, position: int, total: int, mention: str, link_to: Probe | None) -> str:
    head = f"**Channel test {position}/{total}: {STYLE_NAMES[probe.style]}.**"
    ask = "Reply here with anything, so I can time it."
    if probe.style == "normal":
        return f"🔔 {head} {ask}"
    if probe.style == "mention":
        return f"📣 {head} {mention}, this one pings you. {ask}"
    if probe.style == "silent":
        return f"🔕 {head} This one should arrive without a sound. {ask}"
    if link_to is None or link_to.message is None:
        return f"🔗 {head} (There was no other test message to link to.) {ask}"
    return (
        f"🔗 {head} This link goes to the test in {link_to.channel.mention}: "
        f"{link_to.message.jump_url}\nTap it, check it lands there, then come back and reply here."
    )


def check_history_separation(names_and_ids: list[tuple[str, int]]) -> tuple[bool, str]:
    """Check that Claude's conversation history is kept separately for each channel.

    Looks at the real history store: adds a marker to the first channel's
    history, confirms no other channel can see it, and takes it out again.
    """
    if len(names_and_ids) < 2:
        return True, "only one channel to compare, so nothing to check"
    histories = [(name, llm.history_for(channel_id)) for name, channel_id in names_and_ids]
    distinct = len({id(history) for _, history in histories}) == len(histories)
    sizes = [len(history) for _, history in histories]

    marker = {"role": "user", "content": "lab channels: separation marker"}
    first = histories[0][1]
    first.append(marker)
    try:
        leaked = [
            name
            for (name, history), size in zip(histories[1:], sizes[1:])
            if any(entry is marker for entry in history) or len(history) != size
        ]
    finally:
        first.pop()

    holding = ", ".join(f"#{name} {size}" for (name, _), size in zip(histories, sizes))
    if distinct and not leaked:
        return True, f"separate for each channel (messages held: {holding})"
    return False, f"NOT separate: a message added in #{histories[0][0]} showed up in " + (
        ", ".join(f"#{name}" for name in leaked) or "a shared history"
    )


def build_results(probes: list[Probe], history_ok: bool, history_detail: str) -> list[str]:
    lines = []
    for probe in probes:
        style = STYLE_NAMES[probe.style]
        if probe.problem:
            lines.append(f"⚠️ #{probe.name} ({style}): {probe.problem}")
        elif probe.replied_after is None:
            lines.append(f"❌ #{probe.name} ({style}): no reply within {format_seconds(REPLY_TIMEOUT)}")
        else:
            lines.append(f"✅ #{probe.name} ({style}): replied after {format_seconds(probe.replied_after)}")
    lines.append(f"{'✅' if history_ok else '❌'} Claude history: {history_detail}")
    return lines


async def _run_test(run: Run, probes: list[Probe], delay: int) -> None:
    loop = asyncio.get_running_loop()
    usable = [probe for probe in probes if probe.problem is None]
    everyone_replied = asyncio.Event()

    def waiter(probe: Probe):
        async def on_reply(ctx: Context) -> str:
            probe.replied_after = loop.time() - probe.sent_at
            await ctx.acknowledge("✅")
            if all(p.replied_after is not None for p in usable if p.sent_at is not None):
                everyone_replied.set()
            return f"channel test: replied in #{probe.name} after {format_seconds(probe.replied_after)}"

        return on_reply

    try:
        await asyncio.sleep(delay)
        for position, probe in enumerate(usable, start=1):
            if position > 1:
                await asyncio.sleep(GAP)
            link_to = next((other for other in usable if other is not probe and other.message), None)
            text = test_text(probe, position, len(usable), run.member.mention, link_to)
            try:
                probe.message = await probe.channel.send(
                    text,
                    silent=probe.style == "silent",
                    allowed_mentions=discord.AllowedMentions(users=probe.style == "mention"),
                )
            except discord.HTTPException as error:
                probe.problem = f"couldn't post there ({error.status})"
                continue
            probe.sent_at = loop.time()
            # The user's next message in that channel is the reply we're timing
            registry.expect_message(probe.channel.id, run.user_id, waiter(probe), GAP * len(usable) + REPLY_TIMEOUT)

        if any(probe.sent_at is not None for probe in usable):
            try:
                await asyncio.wait_for(everyone_replied.wait(), REPLY_TIMEOUT)
            except asyncio.TimeoutError:
                pass
    finally:
        for probe in usable:
            if probe.sent_at is not None and probe.replied_after is None:
                registry.cancel_expected(probe.channel.id)

    history_ok, history_detail = check_history_separation(
        [(name, CHANNELS[name]) for name, _ in PLAN if name in CHANNELS]
    )
    lines = build_results(probes, history_ok, history_detail)
    replied = sum(1 for probe in probes if probe.replied_after is not None)

    embed = discord.Embed(
        title=f"📡 Channel test: {replied} of {len(probes)} replied",
        description="\n".join(lines),
        colour=discord.Colour.green() if replied == len(probes) and history_ok else discord.Colour.orange(),
    )
    embed.set_footer(text="Times run from when each message was posted to your reply in that channel")
    try:
        await run.channel.send(embed=embed)
    except discord.HTTPException as error:
        log.warning("Could not post the channel test results: %s", error)
    await record(
        f"channels: {replied} of {len(probes)} replied",
        "\n".join(lines),
        channel_id=getattr(run.channel, "id", None),
        user_id=run.user_id,
    )


async def run_channels(run: Run, delay: int) -> None:
    global _runner
    await run.start()
    if _runner is not None and not _runner.done():
        # Asking again isn't a mistake: say that it is under way
        run.note("a channel test was already running")
        await run.done("⏱️ A channel test is already running. Its results card appears here when it finishes.")
        return

    probes = build_probes(run.client)
    usable = [probe for probe in probes if probe.problem is None]
    if not usable:
        raise LabError(
            "None of the test channels can be used: "
            + "; ".join(f"#{probe.name} {probe.problem}" for probe in probes)
        )

    _runner = asyncio.create_task(_run_test(run, probes, delay), name="lab channels")
    names = ", ".join(f"#{probe.name}" for probe in usable)
    when = f"in {format_seconds(delay)}" if delay else "now"
    run.note(f"scheduled the channel test {when}: {names}")
    await run.done(f"⏱️ Channel test starts {when}: {names}. Reply in each channel as its message arrives.")


KEYWORDS = [
    lab_keyword(
        "lab channels",
        "post a test message in #reminders, #gym, #admin and #inbox (normal, @mention, silent, "
        "cross-channel link), time your reply in each, and check Claude's history is per channel",
        run_channels,
        usage="[delay <seconds>]",
        parse=lambda args: (args.delay(MAX_DELAY),),
        examples=["lab channels", "lab channels delay 60"],
    ),
]
