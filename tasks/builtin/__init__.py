from core.context import Context
from core.llm import clear_history, format_cost
from tasks import registry
from tasks.base import ANY, Keyword, Reaction, Task
from tasks.builtin import commands
from tasks.builtin.views import TestButtons

# A task with more words than this is summarised in the overview
OVERVIEW_LIMIT = 6


async def ping(ctx: Context) -> None:
    await ctx.reply("🏓 Pong!")


async def wish(ctx: Context) -> str:
    """`add to my wishlist: …`: one for the wishlist in his own words (core/wishes.py), kept as said."""
    from core import wishes

    words = " ".join(ctx.args).strip(" :")
    if not words:
        await ctx.reply("✨ Say what to add: `add to my wishlist: plan my day`")
        return "nothing to add"
    await wishes.add_said(ctx.user.id, words)
    await ctx.confirm("✨ On your wishlist")
    return "a wish added"


async def reset(ctx: Context) -> None:
    clear_history(ctx.channel_id)
    await ctx.confirm("🧹 Conversation memory cleared.")


async def buttons(ctx: Context) -> None:
    view = TestButtons()
    view.message = await ctx.reply("🧪 Button test: tap one.", view=view)


async def stats(ctx: Context) -> str:
    stats = await ctx.db.get_stats()
    await ctx.reply_card(
        "📊 All-time stats",
        [
            ("Inputs logged", str(stats["total"])),
            ("Claude replies", str(stats["chats"])),
            ("Errors", str(stats["errors"])),
            ("Tokens", f"{stats['input_tokens']} in / {stats['output_tokens']} out"),
            ("Est. cost", format_cost(stats["cost"])),
        ],
    )
    return f"stats: {stats}"


# ---------------------------------------------------------------------------
# help: always built from the registry, so it can't fall out of date
# ---------------------------------------------------------------------------
def _typed(item) -> str:
    """A word as shown in help: `stats` (or `stat`), with its arguments if it has any."""
    text = f"`{item.name}{' ' + item.usage if item.usage else ''}`"
    if item.aliases:
        text += f" (or {', '.join(f'`{alias}`' for alias in item.aliases)})"
    return text


def _task_lines(entry: registry.TaskCapabilities, full: bool) -> list[str]:
    lines = [f"**{entry.task.label}**"]
    if len(entry.keywords) > OVERVIEW_LIMIT and not full:
        lines.append(", ".join(f"`{keyword.name}`" for keyword in entry.keywords))
        lines.append(f"-# `help {entry.task.name}` explains each one")
    else:
        lines += [f"• {_typed(keyword)}: {keyword.description}" for keyword in entry.keywords]
    if entry.reply_actions:
        lines.append("↩️ Reply to a message with:")
        lines += [f"• {_typed(action)}: {action.description}" for action in entry.reply_actions]
    if entry.reactions:
        lines.append("React to a message with:")
        lines += [f"• {reaction.emoji}: {reaction.description}" for reaction in entry.reactions]
    return lines


def build_overview(ctx: Context) -> str:
    """Everything this user can do in this channel, grouped by task."""
    lines = ["**What I understand here**"]
    for entry in registry.catalogue(ctx.user, ctx.channel_id):
        lines += _task_lines(entry, full=False)
    if registry.app_commands():
        lines.append("-# Slash commands still work too: type `/`.")
    lines.append("Anything else goes to Claude. `help <task or word>` shows details.")
    return "\n".join(lines)


def build_task_help(ctx: Context, task: Task) -> str:
    """One task in full, wherever its words work."""
    entries = registry.catalogue(ctx.user, task_name=task.name)
    if not entries:
        return f"**{task.label}** has nothing you can use."
    lines = _task_lines(entries[0], full=True)
    if task.description:
        lines.insert(1, f"-# {task.description}")
    return "\n".join(lines)


def build_item_help(kind: str, task: Task, item) -> str:
    how = {
        "keyword": "a word to send on its own",
        "reply action": "a word to send as a reply to a message",
        "reaction": "a reaction to add to a message",
    }[kind]
    title = item.emoji if kind == "reaction" else f"`{item.name}{' ' + item.usage if item.usage else ''}`"
    lines = [f"**{title}** · {task.label} · {how}", item.description or "(no description)"]
    if getattr(item, "aliases", None):
        lines.append("Also: " + ", ".join(f"`{alias}`" for alias in item.aliases))
    if item.examples:
        lines.append("Examples: " + ", ".join(f"`{example}`" for example in item.examples))
    if getattr(item, "exact", False):
        lines.append("Must be spelled exactly (no typo correction).")
    lines.append(f"Works: {registry.where(item)} · Needs: `{item.permission}`")
    return "\n".join(lines)


def _help_accepts(args: list[str]) -> bool:
    # "help me write an email" is a message for Claude, not a request for help on "me write…"
    return not args or registry.find(" ".join(args)) is not None


async def help_command(ctx: Context) -> None:
    if not ctx.args:
        await ctx.reply(build_overview(ctx))
        return
    kind, task, item = registry.find(" ".join(ctx.args))
    if kind == "task":
        await ctx.reply(build_task_help(ctx, task))
    else:
        await ctx.reply(build_item_help(kind, task, item))


async def thumbs_up(payload, user) -> str | None:
    """👍 on a message that asks one simple yes: what its button does (core/thumbsup.py)."""
    from core import thumbsup

    return await thumbsup.confirm(payload.message_id, user) or "nothing waited for a yes"


async def thumbs_up_taken_away(payload, user) -> str | None:
    from core import thumbsup

    return await thumbsup.undo(payload.message_id, user)


class BuiltinTask(Task):
    name = "builtin"
    description = "Basic commands: ping, reset, buttons, stats and help"
    icon = "⚙️"

    async def startup(self, client) -> None:
        # #commands is written from the registry, which is complete by now
        await commands.update()

    def reactions(self) -> list[Reaction]:
        from core import thumbsup

        if not thumbsup.enabled():
            return []
        return [
            Reaction(
                thumbsup.THUMBS_UP,
                "yes to a message that asks one thing: a dose's reminder (taken), a reminder or an expiry (done), "
                "a routine's own card (all of it done). Remove the reaction to undo it where it can be",
                thumbs_up,
                examples=[f"react {thumbsup.THUMBS_UP} to a dose's reminder"],
                undo=thumbs_up_taken_away,
                tracks=thumbsup.tracked,
            ),
        ]

    def keywords(self) -> list[Keyword]:
        return [
            Keyword("ping", "check the bot is alive", ping, examples=["ping"]),
            Keyword(
                ["add to my wishlist", "add to wishlist"],
                "something you wish the bot could do, kept for the next brainstorm",
                wish,
                examples=["add to my wishlist: plan my day"],
                channels=ANY,
                takes_args=True,
                usage="[what you wish it could do]",
                exact=True,
            ),
            Keyword(
                ["reset", "clear", "clear chat", "wipe"],
                "clear conversation memory",
                reset,
                examples=["reset", "clear chat"],
                exact=True,
            ),
            Keyword("buttons", "interactive button test", buttons, examples=["buttons"]),
            Keyword(["stats", "stat"], "all-time usage totals", stats, examples=["stats"]),
            Keyword(
                "help",
                "show this list, or details for one task or word",
                help_command,
                examples=["help", "help lab", "help stats"],
                channels=ANY,
                takes_args=True,
                usage="[task or word]",
                accepts=_help_accepts,
            ),
        ]


task = BuiltinTask()
