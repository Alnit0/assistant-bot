import logging

import discord

from core import cards, discord_utils
from core.surface import Failed, Gone, Name, Place, Refused
from interfaces.discord import render

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The door's verbs (core/surface.py), on Discord: the shared client is used
# here and, for the core, nowhere else. Discord's errors stop here: a
# NotFound is `Gone`, any other HTTPException is `Failed` with its status
# and code.
# ---------------------------------------------------------------------------
MESSAGE_TYPES = frozenset(
    {
        discord.ChannelType.text,
        discord.ChannelType.news,
        discord.ChannelType.public_thread,
        discord.ChannelType.private_thread,
        discord.ChannelType.news_thread,
        discord.ChannelType.private,
        discord.ChannelType.group,
    }
)


def _failed(error: discord.HTTPException) -> Failed:
    kind = Gone if isinstance(error, discord.NotFound) else Failed
    return kind(str(error), getattr(error, "status", None), getattr(error, "code", None))


def _client():
    return discord_utils.client


def _channel(channel_id: int | None):
    client = _client()
    return client.get_channel(channel_id) if client is not None and channel_id else None


def _must(channel_id: int | None):
    channel = _channel(channel_id)
    if channel is None:
        raise Failed(f"channel {channel_id} can't be found")
    return channel


# --- finding out ------------------------------------------------------------------------------------------------------
def connected() -> bool:
    return _client() is not None


def me() -> int | None:
    return getattr(getattr(_client(), "user", None), "id", None)


def raw_place(channel_id: int | None):
    return _channel(channel_id)


def holds_messages(channel) -> bool:
    """True for a channel whose pins and history can be read: a text or news
    channel, a thread (a forum's post is one) or a DM. False for a forum,
    voice, stage or category channel."""
    return getattr(channel, "type", None) in MESSAGE_TYPES


def place(channel_id: int | None) -> Place | None:
    channel = _channel(channel_id)
    if channel is None:
        return None
    return Place(
        channel_id,
        getattr(channel, "name", None) or str(channel_id),
        getattr(channel, "mention", f"<#{channel_id}>"),
        holds_messages(channel),
        getattr(getattr(channel, "guild", None), "me", None) is not None,
    )


def lacking(channel_id: int, permissions: tuple[str, ...]) -> tuple[str, ...]:
    channel = _channel(channel_id)
    member = getattr(getattr(channel, "guild", None), "me", None)
    if member is None:
        return tuple(permissions)
    allowed = channel.permissions_for(member)
    return tuple(name for name in permissions if not getattr(allowed, name, False))


def mention(account_id: int | None) -> str:
    return f"<@{account_id}>" if account_id else ""


def link(channel_id: int | None, message_id: int | None) -> str:
    guild = getattr(getattr(_channel(channel_id), "guild", None), "id", None)
    return f"https://discord.com/channels/{guild}/{channel_id}/{message_id}" if guild and message_id else ""


async def make_place(beside: int, name: str, reason: str = "") -> int:
    channel = _must(beside)
    guild = getattr(channel, "guild", None)
    if guild is None:
        raise Failed(f"channel {beside} is in no server")
    category = getattr(channel, "category", None)
    there = next((each for each in (category.text_channels if category is not None else guild.text_channels) if each.name == name), None)
    if there is not None:
        return there.id
    try:
        made = await guild.create_text_channel(name, category=category, reason=reason or None)
    except discord.HTTPException as error:
        raise _failed(error) from error
    return made.id


# --- messages ---------------------------------------------------------------------------------------------------------
async def send(channel_id: int, text: str, *, silent: bool = False, suppress_embeds: bool = False) -> int | None:
    more = {name: True for name, wanted in (("silent", silent), ("suppress_embeds", suppress_embeds)) if wanted}
    try:
        message = await _must(channel_id).send(text, **more)
    except discord.HTTPException as error:
        raise _failed(error) from error
    return getattr(message, "id", None)


async def edit(channel_id: int, message_id: int, text: str, *, suppress_embeds: bool = False) -> None:
    try:
        if suppress_embeds:
            # Only a whole message can be told to hide its link previews: a partial one has no
            # `suppress` (discord.py), so the message is fetched first. One more request, for the
            # few messages that are rewritten this way (#commands)
            message = await _must(channel_id).fetch_message(message_id)
            await message.edit(content=text, suppress=True)
        else:
            await _must(channel_id).get_partial_message(message_id).edit(content=text)
    except discord.HTTPException as error:
        raise _failed(error) from error


async def delete(channel_id: int, message_id: int) -> None:
    try:
        await _must(channel_id).get_partial_message(message_id).delete()
    except discord.HTTPException as error:
        raise _failed(error) from error


async def delete_many(channel_id: int, message_ids: list[int], reason: str = "") -> None:
    try:
        await _must(channel_id).delete_messages([discord.Object(id=message_id) for message_id in message_ids], reason=reason)
    except discord.HTTPException as error:
        raise _failed(error) from error


async def fetch(channel_id: int, message_id: int):
    try:
        return await _must(channel_id).fetch_message(message_id)
    except discord.HTTPException as error:
        raise _failed(error) from error


async def history(channel_id: int, *, limit: int | None = None, after=None, oldest_first: bool = False) -> list:
    more = {name: value for name, value in (("after", after), ("oldest_first", oldest_first)) if value}
    try:
        return [message async for message in _must(channel_id).history(limit=limit, **more)]
    except discord.HTTPException as error:
        raise _failed(error) from error


async def pin(channel_id: int, message_id: int, pinned: bool, reason: str = "") -> None:
    message = _must(channel_id).get_partial_message(message_id)
    try:
        if pinned:
            await message.pin(reason=reason)
        else:
            await message.unpin(reason=reason)
    except discord.HTTPException as error:
        raise _failed(error) from error


async def react(channel_id: int, message_id: int, emoji: str) -> None:
    try:
        await _must(channel_id).get_partial_message(message_id).add_reaction(emoji)
    except discord.HTTPException as error:
        raise _failed(error) from error


async def unreact(channel_id: int, message_id: int, emoji: str) -> None:
    try:
        await _must(channel_id).get_partial_message(message_id).remove_reaction(emoji, _client().user)
    except discord.HTTPException as error:
        raise _failed(error) from error


# --- cards ------------------------------------------------------------------------------------------------------------
def drawn(card):
    return render.reply_view(card)


def answer(source) -> render.Answer:
    return render.Answer(source)


async def send_card(channel_id: int, card, text: str, *, silent: bool = False) -> int | None:
    channel = _must(channel_id)
    built = render.view(card)
    try:
        if card.embeds:
            more = {"view": built} if built is not None else {}
            message = await channel.send(render.heading(card), embeds=render.embeds(card), silent=silent, **more)
        elif cards.designed(card):
            message = await channel.send(view=render.layout_view(card.layout), silent=silent)
        elif built is None:
            message = await channel.send(text, silent=silent)
        else:
            message = await channel.send(text, view=built, silent=silent)
    except discord.HTTPException as error:
        raise _failed(error) from error
    return message.id


async def edit_card(channel_id: int, message_id: int, card, plain) -> None:
    message = _must(channel_id).get_partial_message(message_id)
    try:
        if cards.designed(card) or card.embeds:
            # Embeds on a message that is Components V2 are refused (400): the plain words, as a layout, below
            try:
                await message.edit(**render.drawn(card))
                return
            except discord.HTTPException as error:
                if not card.embeds or error.status != 400:
                    raise
                log.info("Card %s could not take embeds (%s): rewriting it as a layout", message_id, error)
                await message.edit(**render.drawn(plain, was_designed=True))
                return
        try:
            await message.edit(**render.drawn(plain))
        except discord.NotFound:
            raise
        except discord.HTTPException as error:
            if error.status != 400:
                raise
            # The message is Components V2 (it was drawn while CARDS_V2 was on), and one can
            # never go back to plain text: the same words and buttons, as a layout
            log.info("Card %s could not be rewritten as plain text (%s): rewriting it as a layout", message_id, error)
            await message.edit(**render.drawn(plain, was_designed=True))
    except discord.HTTPException as error:
        raise _failed(error) from error


# --- the bot itself ---------------------------------------------------------------------------------------------------
async def status(line: str) -> None:
    try:
        await _client().change_presence(activity=discord.CustomActivity(name=line) if line else None)
    except discord.HTTPException as error:
        raise _failed(error) from error


def _member(channel_id: int | None):
    return getattr(getattr(_channel(channel_id), "guild", None), "me", None)


def name(channel_id: int | None) -> Name | None:
    member = _member(channel_id)
    if member is None:
        return None
    return Name(member.nick or member.name, bool(member.guild_permissions.change_nickname))


async def rename(channel_id: int, wanted: str, reason: str = "") -> None:
    member = _member(channel_id)
    if member is None:
        raise Failed("the server was not found")
    try:
        await member.edit(nick=wanted, reason=reason)
    except discord.HTTPException as error:
        raise _failed(error) from error


async def who(token: str) -> tuple[int, str]:
    """HTTP only: nothing is connected to the gateway, so the account does not
    come online and nothing is received or posted."""
    client = discord.Client(intents=discord.Intents.none())
    try:
        await client.login(token)
        return client.user.id, str(client.user)
    except discord.LoginFailure as error:
        raise Refused(str(error)) from error
    except discord.HTTPException as error:
        raise _failed(error) from error
    finally:
        await client.close()
