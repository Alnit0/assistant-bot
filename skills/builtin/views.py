import logging
import random

import discord

from core.config import BUTTON_TIMEOUT, INBOX_CHANNEL_ID
from core.database import log_received, log_result
from core.discord_utils import log_simple, report_interaction_error, safe_reply
from core.permissions import is_allowed
from core.users import get_user_by_discord_id

log = logging.getLogger("assistant")


# ---------------------------------------------------------------------------
# Interactive buttons (test)
# ---------------------------------------------------------------------------
class TestButtons(discord.ui.View):
    """A message with tappable buttons, to test interactions on mobile."""

    def __init__(self):
        super().__init__(timeout=BUTTON_TIMEOUT)
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only you can press the buttons
        user = await get_user_by_discord_id(interaction.user.id)
        if not is_allowed(user, "button"):
            await safe_reply(interaction, "These buttons aren't for you.")
            return False
        # Remember who pressed it, for the log
        interaction.extras["user_id"] = user.id
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        await report_interaction_error(interaction, error, "Button failed")

    async def record(self, interaction: discord.Interaction, label: str, reply: str) -> None:
        row_id = await log_received(
            f"button: {label}",
            "button",
            channel_id=INBOX_CHANNEL_ID,
            user_id=interaction.extras.get("user_id"),
        )
        await log_result(row_id, reply=reply, status="ok")
        log.info("Button pressed: %s", label)
        await log_simple(f"🔘 Button: {label}", reply)

    @discord.ui.button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        reply = "✅ Confirmed. Buttons disabled."
        await interaction.response.edit_message(content=reply, view=self)
        self.stop()
        await self.record(interaction, "Confirm", reply)

    @discord.ui.button(label="Roll", emoji="🎲", style=discord.ButtonStyle.primary)
    async def roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        result = random.randint(1, 6)
        reply = f"🎲 You rolled a **{result}**."
        # Ephemeral: only you can see it, and it can be dismissed
        await interaction.response.send_message(reply, ephemeral=True)
        await self.record(interaction, "Roll", reply)

    @discord.ui.button(label="Wave", emoji="👋", style=discord.ButtonStyle.secondary)
    async def wave(self, interaction: discord.Interaction, button: discord.ui.Button):
        reply = "👋 Hello from Hive!"
        await interaction.response.send_message(reply)
        await self.record(interaction, "Wave", reply)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="⌛ Buttons expired.", view=self)
            except discord.HTTPException:
                pass
