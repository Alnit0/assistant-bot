from core.context import Context
from core.llm import format_cost, history
from skills import registry
from skills.base import ANY, Keyword, Skill
from skills.builtin.views import TestButtons

# A skill with more words than this is summarised in the overview
OVERVIEW_LIMIT = 6


async def ping(ctx: Context) -> None:
    await ctx.reply("🏓 Pong!")


async def reset(ctx: Context) -> None:
    history.clear()
    await ctx.reply("🧹 Conversation memory cleared.")


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


def _skill_lines(entry: registry.SkillCapabilities, full: bool) -> list[str]:
    lines = [f"**{entry.skill.name.capitalize()}**"]
    if len(entry.keywords) > OVERVIEW_LIMIT and not full:
        lines.append(", ".join(f"`{keyword.name}`" for keyword in entry.keywords))
        lines.append(f"-# `help {entry.skill.name}` explains each one")
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
    """Everything this user can do in this channel, grouped by skill."""
    lines = ["**What I understand here**"]
    for entry in registry.catalogue(ctx.user, ctx.channel_id):
        lines += _skill_lines(entry, full=False)
    if registry.app_commands():
        lines.append("-# Slash commands still work too: type `/`.")
    lines.append("Anything else goes to Claude. `help <skill or word>` shows details.")
    return "\n".join(lines)


def build_skill_help(ctx: Context, skill: Skill) -> str:
    """One skill in full, wherever its words work."""
    entries = registry.catalogue(ctx.user, skill_name=skill.name)
    if not entries:
        return f"**{skill.name.capitalize()}** has nothing you can use."
    lines = _skill_lines(entries[0], full=True)
    if skill.description:
        lines.insert(1, f"-# {skill.description}")
    return "\n".join(lines)


def build_item_help(kind: str, skill: Skill, item) -> str:
    how = {
        "keyword": "a word to send on its own",
        "reply action": "a word to send as a reply to a message",
        "reaction": "a reaction to add to a message",
    }[kind]
    title = item.emoji if kind == "reaction" else f"`{item.name}{' ' + item.usage if item.usage else ''}`"
    lines = [f"**{title}** · {skill.name.capitalize()} · {how}", item.description or "(no description)"]
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
    kind, skill, item = registry.find(" ".join(ctx.args))
    if kind == "skill":
        await ctx.reply(build_skill_help(ctx, skill))
    else:
        await ctx.reply(build_item_help(kind, skill, item))


class BuiltinSkill(Skill):
    name = "builtin"
    description = "Basic commands: ping, reset, buttons, stats and help"

    def keywords(self) -> list[Keyword]:
        return [
            Keyword("ping", "check the bot is alive", ping, examples=["ping"]),
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
                "show this list, or details for one skill or word",
                help_command,
                examples=["help", "help lab", "help stats"],
                channels=ANY,
                takes_args=True,
                usage="[skill or word]",
                accepts=_help_accepts,
            ),
        ]


skill = BuiltinSkill()
