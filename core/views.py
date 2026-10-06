import logging
import random

import discord

from core.config import BUTTON_TIMEOUT, INBOX_CHANNEL_ID, OWNER_ID
from core.database import log_received, log_result
from core.discord_utils import log_simple

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
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "These buttons aren't for you.", ephemeral=True
            )
            return False
        return True

    async def record(self, label: str, reply: str) -> None:
        row_id = log_received(f"button: {label}", "button", channel_id=INBOX_CHANNEL_ID)
        log_result(row_id, reply=reply, status="ok")
        log.info("Button pressed: %s", label)
        await log_simple(f"🔘 Button: {label}", reply)

    @discord.ui.button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        reply = "✅ Confirmed. Buttons disabled."
        await interaction.response.edit_message(content=reply, view=self)
        self.stop()
        await self.record("Confirm", reply)

    @discord.ui.button(label="Roll", emoji="🎲", style=discord.ButtonStyle.primary)
    async def roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        result = random.randint(1, 6)
        reply = f"🎲 You rolled a **{result}**."
        # Ephemeral: only you can see it, and it can be dismissed
        await interaction.response.send_message(reply, ephemeral=True)
        await self.record("Roll", reply)

    @discord.ui.button(label="Wave", emoji="👋", style=discord.ButtonStyle.secondary)
    async def wave(self, interaction: discord.Interaction, button: discord.ui.Button):
        reply = "👋 Hello from Hive!"
        await interaction.response.send_message(reply)
        await self.record("Wave", reply)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="⌛ Buttons expired.", view=self)
            except discord.HTTPException:
                pass
