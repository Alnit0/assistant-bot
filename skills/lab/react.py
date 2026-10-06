import logging
from dataclasses import dataclass
from datetime import datetime

import discord

from core.config import now_nz
from core.debounce import Debouncer
from core.permissions import is_allowed
from core.users import get_user_by_discord_id
from skills.lab.common import Run, SlashRun, lab, lab_keyword, record

log = logging.getLogger("assistant")

# Plain colours, so the test can never collide with an emoji that does something
PRESETS = ["🔴", "🟢", "🔵", "🟡"]
QUIET_SECONDS = 15  # how long reactions must stop for before the message is updated
MAX_TIMELINE = 20  # most recent changes shown; a message only holds 2,000 characters


@dataclass(frozen=True)
class Change:
    at: datetime
    discord_user_id: int
    user_id: int  # our users.id
    emoji: str
    added: bool
    message_id: int
    channel_id: int


# Test messages being watched, with every change seen so far. In memory only:
# a restart forgets them.
_timelines: dict[int, list[Change]] = {}
_client: discord.Client | None = None


def bind(client: discord.Client) -> None:
    global _client
    _client = client


def _plain(emoji) -> str:
    # Discord sometimes drops the invisible "emoji style" character
    return str(emoji).replace("️", "")


def final_counts(reactions) -> dict[str, int]:
    """How many people (not counting the bot) have each emoji on the message now."""
    counts = {emoji: 0 for emoji in PRESETS}
    names = {_plain(emoji): emoji for emoji in PRESETS}
    for reaction in reactions:
        if _plain(reaction.emoji) == "✅":
            continue
        emoji = names.get(_plain(reaction.emoji), str(reaction.emoji))
        counts[emoji] = reaction.count - (1 if reaction.me else 0)
    return counts


def build_summary(counts: dict[str, int], timeline: list[Change]) -> str:
    lines = [
        "📊 **Reaction test: settled**",
        "Final state: " + "   ".join(f"{emoji} ×{count}" for emoji, count in counts.items()),
        f"Timeline ({len(timeline)} change{'' if len(timeline) == 1 else 's'}):",
    ]
    shown = timeline[-MAX_TIMELINE:]
    if len(shown) < len(timeline):
        lines.append(f"-# … {len(timeline) - len(shown)} earlier not shown")
    for change in shown:
        sign = "+" if change.added else "−"
        lines.append(
            f"`{sign}` {change.emoji} <@{change.discord_user_id}> <t:{int(change.at.timestamp())}:T>"
        )
    lines.append(f"-# Updated after {QUIET_SECONDS}s of quiet. React again to add to the timeline.")
    return "\n".join(lines)


async def _on_quiet(changes: list[Change]) -> None:
    """Things have gone quiet: update every test message that was touched."""
    touched = dict.fromkeys((change.message_id, change.channel_id) for change in changes)
    for message_id, channel_id in touched:
        timeline = _timelines.get(message_id)
        if timeline is None:
            continue
        channel = _client.get_channel(channel_id)
        try:
            message = await channel.fetch_message(message_id)
            counts = final_counts(message.reactions)
            await message.edit(
                content=build_summary(counts, timeline),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await message.add_reaction("✅")
        except discord.NotFound:
            # The test message was deleted
            del _timelines[message_id]
            continue
        except discord.HTTPException as error:
            log.warning("Could not update the reaction test message: %s", error)
            continue

        state = ", ".join(f"{emoji} ×{count}" for emoji, count in counts.items())
        batch = [change for change in changes if change.message_id == message_id]
        await record(
            "react: settled",
            f"{len(batch)} change(s) in this burst, {len(timeline)} in total. Final: {state}",
            channel_id=channel_id,
            message_id=message_id,
            user_id=batch[-1].user_id,
        )


# One timer for all test messages: any reaction on any of them restarts it
debouncer = Debouncer(QUIET_SECONDS, _on_quiet, name="lab reactions")


async def _on_change(payload: discord.RawReactionActionEvent, added: bool) -> None:
    if payload.message_id not in _timelines:
        return
    user = await get_user_by_discord_id(payload.user_id)
    if not is_allowed(user, "lab"):
        return
    change = Change(
        at=now_nz(),
        discord_user_id=payload.user_id,
        user_id=user.id,
        emoji=str(payload.emoji),
        added=added,
        message_id=payload.message_id,
        channel_id=payload.channel_id,
    )
    _timelines[payload.message_id].append(change)
    debouncer.trigger(change)


async def on_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    await _on_change(payload, added=True)


async def on_reaction_remove(payload: discord.RawReactionActionEvent) -> None:
    await _on_change(payload, added=False)


async def run_react(run: Run) -> None:
    await run.start()
    message = await run.channel.send(
        "🧪 **Reaction test**\n"
        "Add and remove reactions on this message, in any order.\n"
        f"When nothing has changed for {QUIET_SECONDS} seconds, I'll replace this text with "
        "the final state and a timeline, then add ✅."
    )
    _timelines[message.id] = []
    for emoji in PRESETS:
        await message.add_reaction(emoji)

    run.note(f"posted a reaction test with {' '.join(PRESETS)}")
    await run.done("Reaction test posted.")


@lab.command(name="react", description="Reaction test: react, wait 15 seconds, see the summary")
async def react(interaction: discord.Interaction):
    await run_react(SlashRun(interaction))


KEYWORDS = [
    lab_keyword(
        "lab react",
        "reaction test: react, wait 15 seconds, see the final state and a timeline",
        run_react,
    ),
]
