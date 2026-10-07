import asyncio
import importlib
import json
import logging
import pkgutil
import time
from dataclasses import dataclass

import discord

import skills
from core import scheduler
from core.config import CHANNELS, ENABLED_SKILLS
from core.context import Context
from core import database, devmode, discord_utils, lifecycle, reactions, tools
from core.database import log_received, log_result
from core.debounce import Debouncer
from core.discord_utils import log_error, log_simple
from core.errors import UserError
from core.permissions import is_allowed
from core.router import Router
from core.users import User, get_user_by_discord_id
from skills.base import ANY, Keyword, Reaction, ReplyAction, Skill

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Registry
#
# Every package in skills/ is a skill: its __init__.py exposes a `skill` object
# (a Skill subclass instance). A skill that can't be loaded is skipped and
# reported, never allowed to stop the bot.
#
# The registry is also the one place that knows everything the bot can do:
# dispatch, `help` and Claude's capability list are all read from it.
# ---------------------------------------------------------------------------
_skills: list[Skill] = []
_keywords: list[tuple[Skill, Keyword]] = []
_reply_actions: list[tuple[Skill, ReplyAction]] = []
_reactions: dict[str, tuple[Skill, Reaction]] = {}
_events: dict[str, list[tuple[Skill, object]]] = {}
_app_commands: list = []
_problems: list[str] = []
_undocumented: list[str] = []

_keyword_router = Router()
_reply_router = Router()


def _emoji_key(emoji) -> str:
    # Discord sometimes drops the invisible "emoji style" character, so ignore it
    return str(emoji).replace("️", "")


def discover() -> list[str]:
    """Names of the skill packages in skills/, with builtin first."""
    names = [
        module.name
        for module in pkgutil.iter_modules(skills.__path__)
        if module.ispkg and not module.name.startswith("_")
    ]
    return sorted(names, key=lambda name: (name != "builtin", name))


def _problem(message: str) -> None:
    log.error("Skill problem: %s", message)
    _problems.append(message)


def _channel_names(item) -> list[str]:
    return [item.channels] if isinstance(item.channels, str) else list(item.channels)


def _check_registration(skill: Skill, kind: str, item) -> None:
    """Report a registration that doesn't describe itself or names an unknown channel."""
    if not (item.description or "").strip():
        _undocumented.append(f"{skill.name}: {kind} {item.name}")
    for name in _channel_names(item):
        if name != ANY and name not in CHANNELS:
            _problem(f"{skill.name}: {kind} {item.name} names channel '{name}', which isn't set in .env")
    # Claude runs words as tools, and a tool has to know its arguments
    if skill.exposes_tools and getattr(item, "tool", False) and getattr(item, "takes_args", False) and not item.params:
        _problem(f"{skill.name}: {kind} {item.name} takes arguments but lists no `params` for Claude")


def _register_words(router: Router, skill: Skill, kind: str, item) -> None:
    entry = (skill, item)
    for word in item.words:
        owner = router.owner(word)
        if owner is not None:
            _problem(f"{skill.name}: {kind} `{word}` already belongs to {owner[0].name}")
            continue
        router.add(word, entry, takes_args=item.takes_args, exact=item.exact)
    if getattr(item, "pattern", None):
        router.add_pattern(item.pattern, entry)


def load() -> None:
    """Import the enabled skills and register what they provide.

    Blocking: runs once at startup, before the event loop.
    """
    global _keyword_router, _reply_router
    _skills.clear()
    _keywords.clear()
    _reply_actions.clear()
    _reactions.clear()
    _events.clear()
    _app_commands.clear()
    _problems.clear()
    _undocumented.clear()
    _keyword_router = Router()
    _reply_router = Router()

    available = discover()
    if ENABLED_SKILLS is None:
        wanted = available
    else:
        wanted = [name for name in available if name in ENABLED_SKILLS]
        for name in ENABLED_SKILLS:
            if name not in available:
                _problem(f"{name}: listed in ENABLED_SKILLS but there is no skills/{name}/")

    for name in wanted:
        try:
            module = importlib.import_module(f"skills.{name}")
            skill = getattr(module, "skill", None)
            if not isinstance(skill, Skill):
                raise TypeError(f"skills/{name}/__init__.py must define `skill`, a Skill instance")
            if skill.name != name:
                raise ValueError(f"skill.name is {skill.name!r} but the folder is {name!r}")
            keywords = skill.keywords()
            reply_actions = skill.reply_actions()
            reactions = skill.reactions()
            job_handlers = skill.job_handlers()
            events = skill.events()
            slash_commands = skill.app_commands()
            skill.migrations()
        except Exception as error:
            log.exception("Could not load skill %s", name)
            _problems.append(f"{name}: {error!r}")
            continue

        _skills.append(skill)
        for keyword in keywords:
            _check_registration(skill, "keyword", keyword)
            _register_words(_keyword_router, skill, "keyword", keyword)
            _keywords.append((skill, keyword))
        for action in reply_actions:
            _check_registration(skill, "reply action", action)
            _register_words(_reply_router, skill, "reply action", action)
            _reply_actions.append((skill, action))
        for reaction in reactions:
            _check_registration(skill, "reaction", reaction)
            key = _emoji_key(reaction.emoji)
            if key in _reactions:
                _problem(f"{name}: reaction {reaction.emoji} already belongs to {_reactions[key][0].name}")
                continue
            _reactions[key] = (skill, reaction)
        for kind, handler in job_handlers.items():
            scheduler.register_handler(skill.name, kind, handler)
        for event, handler in events.items():
            _events.setdefault(event, []).append((skill, handler))
        _app_commands.extend(slash_commands)

    log.info("Skills loaded: %s", summary())
    if _undocumented:
        log.warning("Registrations with no description: %s", "; ".join(_undocumented))


def loaded_skills() -> list[Skill]:
    return list(_skills)


def problems() -> list[str]:
    """Anything that was skipped while loading, for the startup log."""
    return list(_problems)


def missing_descriptions() -> list[str]:
    """Registrations that don't describe themselves, for the startup warning."""
    return list(_undocumented)


def app_commands() -> list:
    """Every loaded skill's slash command groups and context menus."""
    return list(_app_commands)


def skill_migrations() -> dict[str, list]:
    """Each loaded skill's migrations, for core.migrations.migrate."""
    return {skill.name: skill.migrations() for skill in _skills if skill.migrations()}


def summary() -> str:
    """One line for the startup log, e.g. "builtin (5 words), archive (2 reply actions, 1 reaction)"."""

    def count(number: int, noun: str) -> str:
        return f"{number} {noun}{'' if number == 1 else 's'}"

    parts = []
    for skill in _skills:
        words = sum(1 for owner, _ in _keywords if owner is skill)
        replies = sum(1 for owner, _ in _reply_actions if owner is skill)
        reactions = sum(1 for owner, _ in _reactions.values() if owner is skill)
        counts = [count(words, "word")] if words or not (replies or reactions) else []
        if replies:
            counts.append(count(replies, "reply action"))
        if reactions:
            counts.append(count(reactions, "reaction"))
        parts.append(f"{skill.name} ({', '.join(counts)})")
    return ", ".join(parts) or "none"


# ---------------------------------------------------------------------------
# Lifecycle and events
# ---------------------------------------------------------------------------
def setup(client: discord.Client) -> None:
    """Let each skill register persistent views before the bot connects. Never fatal."""
    for skill in _skills:
        try:
            skill.setup(client)
        except Exception as error:
            log.exception("Skill setup failed: %s", skill.name)
            _problems.append(f"{skill.name}: setup failed: {error!r}")


async def startup(client: discord.Client) -> None:
    """Give each skill its turn once the bot is connected. A failure is reported, not fatal."""
    for skill in _skills:
        try:
            await skill.startup(client)
        except Exception as error:
            log.exception("Skill startup failed: %s", skill.name)
            _problems.append(f"{skill.name}: startup failed: {error!r}")


async def emit(event: str, *args) -> None:
    """Pass a Discord event on to every skill that asked for it."""
    for skill, handler in _events.get(event, []):
        try:
            await handler(*args)
        except Exception as error:
            log.exception("Skill %s failed handling %s", skill.name, event)
            await log_error(f"Skill event failed: {skill.name} / {event}", repr(error))


async def declared_class(message_id: int) -> lifecycle.MessageClass | None:
    """What a skill says one of its own messages is (Live, Alert), or None if
    no skill claims it. For `dev inspect`."""
    for skill in _skills:
        try:
            found = await skill.message_class(message_id)
        except Exception:
            log.exception("Skill %s failed classifying message %s", skill.name, message_id)
            continue
        if found is not None:
            return found
    return None


@dataclass(frozen=True)
class ActionResult:
    """How one input ended. Sent to skills as the "action_finished" event."""

    kind: str  # "command", "reply_action", "reaction" or "chat"
    name: str  # the keyword, reply word or emoji ("chat" for a chat with Claude)
    status: str  # "ok", "error" or "denied"
    user_id: int  # our users.id
    channel_id: int
    command_deleted: bool = False  # the user's command message was tidied away
    reply: str = ""  # what was recorded as the reply


# ---------------------------------------------------------------------------
# Where and for whom a registration works
# ---------------------------------------------------------------------------
def works_in(item, channel_id: int) -> bool:
    names = _channel_names(item)
    return ANY in names or any(CHANNELS.get(name) == channel_id for name in names)


def where(item) -> str:
    """Where a registration works, in words: "anywhere" or "#inbox, #gym"."""
    names = _channel_names(item)
    return "anywhere" if ANY in names else ", ".join(f"#{name}" for name in names)


# ---------------------------------------------------------------------------
# Dispatch: typed words and reply actions
# ---------------------------------------------------------------------------
async def _run(
    ctx: Context, *, kind: str, name: str, title: str, permission: str, call, keep_command: bool,
    mark_failure: bool = True,
) -> tuple[str, str]:
    """Log the input, check permission, run the handler, record what happened.
    Returns (status, what was recorded): status is "ok", "error" or "denied".

    How it ends is the same for every word and reply action:
    - Worked: the user's command message is deleted (unless the registration
      keeps it), and if the handler showed nothing a short confirmation is
      posted that deletes itself.
    - Didn't work: the command message stays and gets a ⚠️ reaction. The
      details go to #bot-log, not the channel.

    A tool call from Claude comes through here too, with `mark_failure` off:
    the user's message was chat, not a command, so it gets no ⚠️, and the
    reason goes back to Claude to explain.
    """
    row_id = await log_received(ctx.text, kind, ctx.message_id, ctx.channel_id, user_id=ctx.user.id)
    started = time.perf_counter()

    async def finished(status: str, reply: str = "", command_deleted: bool = False) -> None:
        await devmode.debug(
            f"{kind}: {name}",
            [
                f"Trigger: `{ctx.text}` in <#{ctx.channel_id}>",
                f"Outcome: {status} in {time.perf_counter() - started:.2f}s",
                f"Command message: {'deleted' if command_deleted else 'kept'}",
            ],
        )
        await emit(
            "action_finished",
            ActionResult(kind, name, status, ctx.user.id, ctx.channel_id, command_deleted, reply),
        )

    async def failed() -> None:
        if mark_failure:
            await ctx.mark_failed()

    if not is_allowed(ctx.user, permission):
        await log_result(row_id, reply="not allowed", status="denied")
        await failed()
        await ctx.log_error(f"Command refused: {name}", f"Needs permission `{permission}`.", ctx.text)
        await finished("denied")
        return "denied", "The user is not allowed to do that."

    try:
        reply = await call()
    except UserError as error:
        # The user can fix this one: no traceback needed
        log.info("%s not done: %s", name, error)
        await log_result(row_id, status="error", error=str(error))
        await failed()
        await ctx.log_error(f"Command failed: {name}", str(error), ctx.text)
        await finished("error")
        return "error", str(error)
    except Exception as error:
        log.exception("Command failed: %s", name)
        await log_result(row_id, status="error", error=repr(error))
        await failed()
        await ctx.log_error(f"Command failed: {name}", repr(error), ctx.text)
        await finished("error")
        return "error", repr(error)

    if not ctx.replies:
        # The handler showed nothing in the channel, so say that it happened
        await ctx.confirm(f"✅ Done: {name}")
    if reply is None:
        reply = "\n".join(ctx.replies)
    await log_result(row_id, reply=reply, status="ok")
    await ctx.log(title, reply)
    command_deleted = False if keep_command else await ctx.delete_command()
    await finished("ok", reply, command_deleted)
    return "ok", reply


async def dispatch_keyword(ctx: Context) -> bool:
    """Run the keyword this input is. Returns False if it isn't one (here)."""
    match = _keyword_router.match(ctx.text)
    if match is None:
        return False
    _, keyword = match.entry
    if not works_in(keyword, ctx.channel_id):
        return False
    if keyword.accepts is not None and not keyword.accepts(match.args):
        return False
    ctx.args = match.args

    async def call():
        if match.corrected:
            await ctx.note(f"-# Read as: {match.phrase}")
        return await keyword.handler(ctx)

    await _run(
        ctx,
        kind="command",
        name=keyword.name,
        title=f"⌨️ Command: {keyword.name}",
        permission=keyword.permission,
        call=call,
        keep_command=keyword.keep_command,
    )
    return True


async def dispatch_reply_action(ctx: Context) -> bool:
    """Run the reply action this input is. Returns False if it isn't a reply, or not an action."""
    if not ctx.is_reply:
        return False
    # Filler words are fine on a reply: "pin this", "please archive it"
    match = _reply_router.match(ctx.text, fillers=True)
    if match is None:
        return False
    _, action = match.entry
    if not works_in(action, ctx.channel_id):
        return False
    ctx.args = match.args
    if action.applies_to is not None and not await action.applies_to(ctx):
        ctx.args = []
        return False

    async def call():
        target = await ctx.fetch_reply_target()
        if target is None:
            raise UserError("I can't find the message you replied to.")
        if action.validate is not None:
            try:
                action.validate(target)
            except UserError as error:
                # Can't be done to that message: say why, briefly, as well as the ⚠️
                await ctx.note(f"{reactions.FAILED_EMOJI} {error}")
                raise
        if match.corrected:
            await ctx.note(f"-# Read as: {match.phrase}")
        return await action.handler(ctx, target)

    await _run(
        ctx,
        kind="reply_action",
        name=action.name,
        title=f"↩️ Reply action: {action.name}",
        permission=action.permission,
        call=call,
        keep_command=action.keep_command,
    )
    return True


# ---------------------------------------------------------------------------
# Tools for Claude: every word and reply action, generated from what it says
# about itself (core/tools.py builds the schemas). skills/toolcalls.py decides
# when a call may run; when it may, it runs here, down the same path as a
# typed word, so it is logged and permission-checked in exactly the same way.
# ---------------------------------------------------------------------------
def _channel_name(channel_id: int | None) -> str | None:
    for name, known_id in CHANNELS.items():
        if known_id == channel_id:
            return name
    return None


def _spec(skill: Skill, kind: str, item) -> tools.ToolSpec:
    is_reply = kind == tools.REPLY_ACTION
    if is_reply:
        description = f"Message action: {item.description}."
    else:
        description = f"Same as the user typing `{describe_words(item)}`: {item.description}."
    if item.destructive:
        description += " The user is asked to confirm with buttons before it runs."
    return tools.ToolSpec(
        name=tools.tool_name(kind, item.name),
        description=description,
        schema=tools.build_schema(item.params, propose=not item.destructive, targets=is_reply),
        kind=kind,
        skill=skill.name,
        item=item,
        has_arguments=bool(item.params),
        priority=item.tool_priority,
        destructive=item.destructive,
    )


def tools_for(user: User | None, channel_id: int | None) -> list[tools.ToolSpec]:
    """The tools Claude may be given for this user in this channel, in a fixed order.

    Filtered the way `help` is (channel and permission), then by each skill's
    own say (the lab never offers any; dev only while dev mode is on) and by
    registrations that opt out with `tool=False`.
    """
    if user is None:
        # catalogue() reads "no user" as "don't filter"; for tools it means nobody is asking
        return []
    channel_name = _channel_name(channel_id)
    specs = []
    for entry in catalogue(user, channel_id):
        if not entry.skill.tools_available(channel_name):
            continue
        specs += [_spec(entry.skill, tools.KEYWORD, item) for item in entry.keywords if item.tool]
        specs += [_spec(entry.skill, tools.REPLY_ACTION, item) for item in entry.reply_actions if item.tool]
    return specs


@dataclass(frozen=True)
class ToolOutcome:
    status: str  # "ok", "error" or "denied"
    text: str  # what was recorded, or why it failed
    confirmations: list[str]  # what the handler would have confirmed, if they were collected


async def run_tool(
    ctx: Context, spec: tools.ToolSpec, value: dict, target: discord.Message | None = None, *, collect: bool = False
) -> ToolOutcome:
    """Run one tool call that has been cleared to run.

    `ctx` is the user's chat message; the call gets its own context, whose text
    is the call itself (that is what is logged as the input). `target` is the
    message a reply action acts on. With `collect`, confirmations are handed
    back instead of posted, for the caller to show with a preview.
    """
    item = spec.item
    args = tools.to_args(item.params, value)
    call_ctx = Context(
        user=ctx.user,
        channel_id=ctx.channel_id,
        message_id=ctx.message_id,
        text=f"tool: {spec.name} {json.dumps(value, ensure_ascii=False, sort_keys=True)}",
        _channel=ctx._channel,
        args=args,
        _message=ctx._message,
        collect_confirmations=collect,
    )

    async def call():
        if spec.kind == tools.REPLY_ACTION:
            if target is None:
                raise UserError("I can't find the message to act on.")
            if item.validate is not None:
                item.validate(target)
            return await item.handler(call_ctx, target)
        return await item.handler(call_ctx)

    status, text = await _run(
        call_ctx,
        kind="tool",
        name=tools.command_text(item.name, args),
        title=f"🔧 Tool: {item.name}",
        permission=item.permission,
        call=call,
        # The user's message was chat with Claude (Kept), not a command to tidy away
        keep_command=True,
        mark_failure=False,
    )
    return ToolOutcome(status, text, list(call_ctx.collected))


async def run_undo(ctx: Context, spec: tools.ToolSpec, target: discord.Message) -> ToolOutcome:
    """Take back a reply action Claude ran (the Undo button), logged like the call was."""
    item = spec.item
    call_ctx = Context(
        user=ctx.user,
        channel_id=ctx.channel_id,
        message_id=ctx.message_id,
        text=f"undo: {spec.name} on message {target.id}",
        _channel=ctx._channel,
        _message=ctx._message,
        collect_confirmations=True,
    )

    async def call():
        shown = await item.undo(call_ctx, target)
        call_ctx.shown(shown)
        return shown

    status, text = await _run(
        call_ctx,
        kind="tool",
        name=f"undo {item.name}",
        title=f"↩️ Undo: {item.name}",
        permission=item.permission,
        call=call,
        keep_command=True,
        mark_failure=False,
    )
    return ToolOutcome(status, text, list(call_ctx.collected))


# ---------------------------------------------------------------------------
# Dispatch: reactions, after a quiet period
#
# A reaction that can't be done to its message (Reaction.validate) is refused
# the moment it is added: ⚠️ and a brief reason, no waiting. For the rest,
# every add and remove of a registered emoji restarts one shared timer. When
# things go quiet we look at where each reaction ended up and compare it with
# what is already applied (core/reactions.py): apply what is new, undo what
# has been taken away. An applied action gets ✅ on the message; when the last
# one on a message is undone, the ✅ goes too.
# ---------------------------------------------------------------------------
def _partial_message(channel_id: int, message_id: int):
    client = discord_utils.client
    channel = client.get_channel(channel_id) if client else None
    return channel.get_partial_message(message_id) if channel is not None else None


async def _mark(channel_id: int, message_id: int, emoji: str, add: bool = True) -> None:
    """Add or remove one of the bot's own marker reactions (✅, ⚠️). Best effort."""
    message = _partial_message(channel_id, message_id)
    if message is None:
        return
    try:
        if add:
            await message.add_reaction(emoji)
        else:
            await message.remove_reaction(emoji, discord_utils.client.user)
    except discord.HTTPException:
        pass  # the message has gone, or we may not react here


async def _reactions_quiet(events: list[tuple[discord.RawReactionActionEvent, bool]]) -> None:
    """Things have gone quiet: bring what is applied into line with the reactions that are there."""
    changes: list[tuple[reactions.Key, bool]] = []
    payloads: dict[reactions.Key, discord.RawReactionActionEvent] = {}
    users: dict[reactions.Key, User] = {}
    people = {
        discord_id: await get_user_by_discord_id(discord_id)
        for discord_id in {payload.user_id for payload, _ in events}
    }

    def works_here(emoji: str, channel_id: int) -> bool:
        entry = _reactions.get(emoji)
        return entry is not None and works_in(entry[1], channel_id)

    def user_id_for(emoji: str, discord_user_id: int) -> int | None:
        user = people[discord_user_id]
        return user.id if is_allowed(user, _reactions[emoji][1].permission) else None

    for payload, added in events:
        change = reactions.Change(
            payload.message_id, payload.channel_id, _emoji_key(payload.emoji), payload.user_id
        )
        # Which changes count is decided in core/reactions.py
        key = reactions.key_for(change, works_here, user_id_for)
        if key is None:
            continue
        changes.append((key, added))
        payloads[key], users[key] = payload, people[payload.user_id]

    final = reactions.final_states(changes)
    applied = await database.run(reactions.db_applied, sorted({key[0] for key in final}))
    to_apply, to_undo = reactions.plan_changes(final, applied)

    def emojis(keys) -> str:
        return ", ".join(f"{key[1]} on {key[0]}" for key in keys) or "none"

    await devmode.debug(
        "Reactions settled",
        [
            f"Trigger: {len(events)} change(s), quiet for {_reaction_debouncer.delay:g}s",
            "Final state: "
            + (", ".join(f"{key[1]} on {key[0]} {'there' if there else 'gone'}" for key, there in final.items()) or "nothing of ours"),
            f"Already applied: {emojis(applied)}",
            f"To apply: {emojis(to_apply)}",
            f"To undo: {emojis(to_undo)}",
        ],
    )
    started = time.perf_counter()
    for key in to_undo:
        await _undo_reaction(key, payloads[key], users[key])
    for key in to_apply:
        await _apply_reaction(key, payloads[key], users[key])
    if to_apply or to_undo:
        await devmode.debug(
            "Reactions handled",
            [f"{len(to_apply)} applied, {len(to_undo)} undone in {time.perf_counter() - started:.2f}s"],
        )


# One timer for all reactions: any change to a registered emoji restarts it. The
# delay is REACTION_DEBOUNCE, unless dev mode has shortened it
_reaction_debouncer = Debouncer(devmode.reaction_debounce, _reactions_quiet, name="reactions")


# Reactions refused on the spot, as (message id, emoji, Discord user id), so that
# taking one off again clears its ⚠️. In memory: a restart forgets them
_refused: set[tuple[int, str, int]] = set()


async def _fetch_message(channel_id: int, message_id: int) -> discord.Message | None:
    client = discord_utils.client
    channel = client.get_channel(channel_id) if client else None
    if channel is None:
        return None
    try:
        return await channel.fetch_message(message_id)
    except discord.HTTPException:
        return None


async def _refuse_reaction(
    skill: Skill, reaction: Reaction, payload: discord.RawReactionActionEvent, user: User, reason: str
) -> None:
    """An invalid reaction: ⚠️ on the message and the reason shown briefly, with no wait."""
    text = f"reaction: {reaction.emoji}"
    row_id = await log_received(text, "reaction", payload.message_id, payload.channel_id, user_id=user.id)
    log.info("Reaction %s refused: %s", reaction.emoji, reason)
    await log_result(row_id, status="error", error=reason)
    await _mark(payload.channel_id, payload.message_id, reactions.FAILED_EMOJI)
    message = _partial_message(payload.channel_id, payload.message_id)
    if message is not None:
        try:
            note = await message.channel.send(
                f"{reactions.FAILED_EMOJI} {reason}", delete_after=lifecycle.delete_after(), silent=True
            )
            lifecycle.note_transient(note.id)
        except discord.HTTPException as error:
            log.info("Could not say why a reaction was refused: %s", error)
    await log_error(f"Reaction refused: {reaction.emoji}", reason, text)
    await emit(
        "action_finished",
        ActionResult("reaction", reaction.emoji, "error", user.id, payload.channel_id),
    )


async def _reaction_is_valid(payload: discord.RawReactionActionEvent) -> bool:
    """Check a reaction the moment it is added. False if it was refused (and dealt with)."""
    skill, reaction = _reactions[_emoji_key(payload.emoji)]
    user = await get_user_by_discord_id(payload.user_id)
    if not reactions.should_validate(
        True,
        reaction.validate is not None,
        works_in(reaction, payload.channel_id),
        is_allowed(user, reaction.permission),
    ):
        return True
    message = await _fetch_message(payload.channel_id, payload.message_id)
    if message is None:
        return True  # can't look at it now: the handler will say what is wrong
    try:
        reaction.validate(message)
    except UserError as error:
        _refused.add((payload.message_id, _emoji_key(payload.emoji), payload.user_id))
        await _refuse_reaction(skill, reaction, payload, user, str(error))
        return False
    return True


async def reaction_changed(payload: discord.RawReactionActionEvent, added: bool) -> None:
    """Note a reaction being added or removed.

    One that can't be done to that message is refused straight away. Only
    valid ones wait out the quiet period, after which their handlers run.
    """
    emoji = _emoji_key(payload.emoji)
    if emoji not in _reactions:
        return
    refused = (payload.message_id, emoji, payload.user_id)
    if added:
        if not await _reaction_is_valid(payload):
            return
    elif refused in _refused:
        # Taking a refused reaction off again: nothing was pending, so just clear the ⚠️
        _refused.discard(refused)
        if not any(message_id == payload.message_id for message_id, _, _ in _refused):
            await _mark(payload.channel_id, payload.message_id, reactions.FAILED_EMOJI, add=False)
        return
    _reaction_debouncer.trigger((payload, added))


async def _apply_reaction(key: reactions.Key, payload: discord.RawReactionActionEvent, user: User) -> None:
    skill, reaction = _reactions[key[1]]
    text = f"reaction: {reaction.emoji}"
    row_id = await log_received(
        text, "reaction", payload.message_id, payload.channel_id, user_id=user.id
    )
    try:
        reply = await reaction.handler(payload, user)
    except Exception as error:
        # Flag the message itself; the details belong in #bot-log, not the channel
        detail = str(error) if isinstance(error, UserError) else repr(error)
        if isinstance(error, UserError):
            log.info("Reaction %s not done: %s", reaction.emoji, error)
        else:
            log.exception("Reaction failed: %s (%s)", reaction.emoji, skill.name)
        await log_result(row_id, status="error", error=detail)
        await _mark(payload.channel_id, payload.message_id, reactions.FAILED_EMOJI)
        await log_error(f"Reaction failed: {reaction.emoji}", detail, text)
        await emit(
            "action_finished",
            ActionResult("reaction", reaction.emoji, "error", user.id, payload.channel_id),
        )
        return

    reply = reply or "done"
    await log_result(row_id, reply=reply, status="ok")
    await log_simple(f"{reaction.emoji} Reaction: {skill.name}", reply)
    if not reaction.destructive:
        # Remember it, so taking the reaction away later can undo it
        await database.run(reactions.db_mark_applied, key, payload.channel_id)
        await _mark(payload.channel_id, payload.message_id, reactions.FAILED_EMOJI, add=False)
        await _mark(payload.channel_id, payload.message_id, reactions.DONE_EMOJI)
    await emit(
        "action_finished",
        ActionResult("reaction", reaction.emoji, "ok", user.id, payload.channel_id, reply=reply),
    )


async def _undo_reaction(key: reactions.Key, payload: discord.RawReactionActionEvent, user: User) -> None:
    skill, reaction = _reactions[key[1]]
    text = f"reaction removed: {reaction.emoji}"
    row_id = await log_received(
        text, "reaction", payload.message_id, payload.channel_id, user_id=user.id
    )
    try:
        reply = (await reaction.undo(payload, user) if reaction.undo is not None else None) or "undone"
    except Exception as error:
        detail = str(error) if isinstance(error, UserError) else repr(error)
        log.exception("Undoing reaction %s failed (%s)", reaction.emoji, skill.name)
        await log_result(row_id, status="error", error=detail)
        await _mark(payload.channel_id, payload.message_id, reactions.FAILED_EMOJI)
        await log_error(f"Undoing reaction failed: {reaction.emoji}", detail, text)
        return

    still_applied = await database.run(reactions.db_forget, key)
    await log_result(row_id, reply=reply, status="ok")
    await log_simple(f"{reaction.emoji} Reaction removed: {skill.name}", reply)
    if still_applied == 0:
        await _mark(payload.channel_id, payload.message_id, reactions.DONE_EMOJI, add=False)


async def dispatch_reaction(payload: discord.RawReactionActionEvent) -> bool:
    """Apply one reaction straight away, without the quiet period (used by tests and tools).

    Returns False if the emoji isn't registered here or the user isn't allowed.
    """
    entry = _reactions.get(_emoji_key(payload.emoji))
    if entry is None or not works_in(entry[1], payload.channel_id):
        return False
    user = await get_user_by_discord_id(payload.user_id)
    if not is_allowed(user, entry[1].permission):
        return False
    await _apply_reaction((payload.message_id, _emoji_key(payload.emoji), user.id), payload, user)
    return True


# ---------------------------------------------------------------------------
# Dispatch: a message a skill is waiting for
# ---------------------------------------------------------------------------
@dataclass
class _Expected:
    user_id: int  # our users.id
    handler: object  # async (ctx) -> str | None
    expires_at: float  # event loop time


_expected: dict[int, _Expected] = {}


def expect_message(channel_id: int, user_id: int, handler, timeout: float) -> None:
    """Hand this user's next message in this channel to `handler(ctx)`, once.

    For a skill that has asked a question and is waiting for the answer. The
    message is still offered to reply actions and keywords first; if it is
    neither, the handler gets it and it does not go to Claude. One waiter per
    channel: a new one replaces the old. Held in memory, so a restart forgets it.
    """
    _expected[channel_id] = _Expected(user_id, handler, asyncio.get_running_loop().time() + timeout)


def cancel_expected(channel_id: int) -> None:
    _expected.pop(channel_id, None)


async def dispatch_expected(ctx: Context) -> bool:
    """Give the message to a waiting skill. Returns False if nobody is waiting for it."""
    waiting = _expected.get(ctx.channel_id)
    if waiting is None:
        return False
    if waiting.expires_at < asyncio.get_running_loop().time():
        del _expected[ctx.channel_id]
        return False
    if waiting.user_id != ctx.user.id:
        return False
    del _expected[ctx.channel_id]

    row_id = await log_received(
        ctx.text, "expected", ctx.message_id, ctx.channel_id, user_id=ctx.user.id
    )
    try:
        reply = await waiting.handler(ctx)
    except Exception as error:
        log.exception("Handler for an expected message failed")
        await log_result(row_id, status="error", error=repr(error))
        await ctx.mark_failed()
        await ctx.log_error("Expected message failed", repr(error), ctx.text)
        return True
    await log_result(row_id, reply=reply or "received", status="ok")
    return True


# ---------------------------------------------------------------------------
# What the bot can do: read by `help` and by Claude's system prompt
# ---------------------------------------------------------------------------
@dataclass
class SkillCapabilities:
    skill: Skill
    keywords: list[Keyword]
    reply_actions: list[ReplyAction]
    reactions: list[Reaction]


def catalogue(
    user: User | None = None, channel_id: int | None = None, skill_name: str | None = None
) -> list[SkillCapabilities]:
    """What each loaded skill offers, in load order.

    With a user, only what they are allowed to use. With a channel, only what
    works there. Skills with nothing left to show are left out.
    """

    def visible(item) -> bool:
        if channel_id is not None and not works_in(item, channel_id):
            return False
        return user is None or is_allowed(user, item.permission)

    result = []
    for skill in _skills:
        if skill_name is not None and skill.name != skill_name:
            continue
        entry = SkillCapabilities(
            skill,
            [item for owner, item in _keywords if owner is skill and visible(item)],
            [item for owner, item in _reply_actions if owner is skill and visible(item)],
            [item for owner, item in _reactions.values() if owner is skill and visible(item)],
        )
        if entry.keywords or entry.reply_actions or entry.reactions:
            result.append(entry)
    return result


def find(term: str) -> tuple[str, Skill, object] | None:
    """Look something up for `help <term>`: a skill, a word, a reply action or an emoji.

    Returns (kind, skill, item) with kind "skill", "keyword", "reply action" or
    "reaction"; item is None for a skill. Aliases and small typos are accepted.
    """
    wanted = term.strip().lower()
    for skill in _skills:
        if skill.name == wanted:
            return ("skill", skill, None)
    for kind, router in (("keyword", _keyword_router), ("reply action", _reply_router)):
        match = router.match(term)
        if match is not None and not match.args:
            skill, item = match.entry
            return (kind, skill, item)
    entry = _reactions.get(_emoji_key(term.strip()))
    if entry is not None:
        return ("reaction", entry[0], entry[1])
    return None


def describe_words(item) -> str:
    """A keyword or reply action as the user types it: "stats (also: stat)"."""
    text = item.name + (f" {item.usage}" if item.usage else "")
    if item.aliases:
        text += f" (also: {', '.join(item.aliases)})"
    return text


def capabilities_text(user: User | None, channel_id: int | None) -> str:
    """The same list `help` shows, as plain text for Claude's system prompt."""
    words, replies, reactions = [], [], []
    for entry in catalogue(user, channel_id):
        words += [f"- {describe_words(item)}: {item.description}" for item in entry.keywords]
        replies += [f"- {describe_words(item)}: {item.description}" for item in entry.reply_actions]
        reactions += [f"- {item.emoji}: {item.description}" for item in entry.reactions]

    sections = []
    if words:
        sections.append("Words to send as a message on their own:\n" + "\n".join(words))
    if replies:
        sections.append("Words to send as a reply to a message, to act on that message:\n" + "\n".join(replies))
    if reactions:
        sections.append("Reactions to add to a message:\n" + "\n".join(reactions))
    return "\n\n".join(sections)
