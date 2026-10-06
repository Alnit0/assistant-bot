from core.context import Context
from core.llm import format_cost, history
from skills import registry
from skills.base import Command, Skill
from skills.builtin.views import TestButtons


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


def build_help() -> str:
    """List every loaded skill's commands: builtin first, then the rest under headings."""
    lines = ["**Commands**"]
    heading = BuiltinSkill.name
    for owner, command in registry.all_commands():
        if owner.name != heading:
            heading = owner.name
            lines.append(f"**{heading.capitalize()}**")
        lines.append(f"• `{command.name}`: {command.description}")
    lines.append("Anything else goes to Claude.")
    return "\n".join(lines)


async def help_command(ctx: Context) -> None:
    await ctx.reply(build_help())


class BuiltinSkill(Skill):
    name = "builtin"
    description = "Basic commands: ping, reset, buttons, stats and help"

    def commands(self) -> list[Command]:
        return [
            Command("ping", "check the bot is alive", ping),
            Command("reset", "clear conversation memory", reset),
            Command("buttons", "interactive button test", buttons),
            Command("stats", "all-time usage totals", stats),
            Command("help", "show this list", help_command),
        ]


skill = BuiltinSkill()
