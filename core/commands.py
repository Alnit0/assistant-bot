import discord

from core.config import now_nz
from core.database import get_stats, log_received, log_result
from core.discord_utils import COLOUR_INFO, log_simple
from core.llm import format_cost, history
from core.users import User
from core.views import TestButtons

HELP_TEXT = (
    "**Commands**\n"
    "• `ping`: check the bot is alive\n"
    "• `reset`: clear conversation memory\n"
    "• `buttons`: interactive button test\n"
    "• `stats`: all-time usage totals\n"
    "• `help`: show this list\n"
    "Anything else goes to Claude."
)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
async def handle_command(message: discord.Message, command: str, user: User) -> bool:
    """Handle built-in commands. Returns True if the message was a command."""
    if command not in {"ping", "reset", "buttons", "stats", "help"}:
        return False

    row_id = await log_received(
        message.content, "command", message.id, message.channel.id, user_id=user.id
    )

    if command == "ping":
        reply = "🏓 Pong!"
        await message.channel.send(reply)

    elif command == "reset":
        history.clear()
        reply = "🧹 Conversation memory cleared."
        await message.channel.send(reply)

    elif command == "buttons":
        reply = "🧪 Button test: tap one."
        view = TestButtons()
        view.message = await message.channel.send(reply, view=view)

    elif command == "stats":
        stats = await get_stats()
        embed = discord.Embed(title="📊 All-time stats", colour=COLOUR_INFO, timestamp=now_nz())
        embed.add_field(name="Inputs logged", value=str(stats["total"]), inline=True)
        embed.add_field(name="Claude replies", value=str(stats["chats"]), inline=True)
        embed.add_field(name="Errors", value=str(stats["errors"]), inline=True)
        embed.add_field(
            name="Tokens",
            value=f"{stats['input_tokens']} in / {stats['output_tokens']} out",
            inline=True,
        )
        embed.add_field(name="Est. cost", value=format_cost(stats["cost"]), inline=True)
        await message.channel.send(embed=embed)
        reply = f"stats: {stats}"

    else:  # help
        reply = HELP_TEXT
        await message.channel.send(reply)

    await log_result(row_id, reply=reply, status="ok")
    await log_simple(f"⌨️ Command: {command}", reply)
    return True
