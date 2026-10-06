import logging
from collections.abc import Awaitable, Callable

import discord

from core.config import CONFIRMATION_SECONDS
from core.database import log_received, log_result
from core.discord_utils import log_error, report_interaction_error, safe_reply
from core.errors import UserError
from core.users import User, get_user_by_discord_id

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Confirmations: "are you sure?" before something that can't easily be undone.
#
# Prompts are held in memory. One left unanswered times out and removes itself;
# one caught by a restart stops working (the user is told so if they press it).
# ---------------------------------------------------------------------------
TIMEOUT_SECONDS = 120


class _Prompt(discord.ui.View):
    def __init__(self, user: User, question: str, on_confirm: Callable[[], Awaitable[str]]):
        super().__init__(timeout=TIMEOUT_SECONDS)
        self.user = user
        self.question = question
        self.on_confirm = on_confirm
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        presser = await get_user_by_discord_id(interaction.user.id)
        if presser is None or presser.id != self.user.id:
            await safe_reply(interaction, "That question isn't for you.")
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        await report_interaction_error(interaction, error, "Confirmation failed")

    async def _remove(self) -> None:
        self.stop()
        if self.message is not None:
            try:
                await self.message.delete()
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Answer first; the action itself may take a moment
        await interaction.response.defer()
        self.stop()
        row_id = await log_received(
            f"confirmed: {self.question}", "confirmation", interaction.message.id,
            interaction.channel_id, user_id=self.user.id,
        )
        try:
            outcome = await self.on_confirm()
        except UserError as error:
            await log_result(row_id, status="error", error=str(error))
            await log_error("Confirmed action failed", str(error), self.question)
            await interaction.message.edit(content=f"⚠️ {error}", view=None, delete_after=CONFIRMATION_SECONDS * 3)
            return
        await log_result(row_id, reply=outcome, status="ok")
        await interaction.message.edit(content=outcome, view=None, delete_after=CONFIRMATION_SECONDS)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self._remove()

    async def on_timeout(self) -> None:
        await self._remove()


async def ask(
    channel: discord.abc.Messageable,
    user: User,
    question: str,
    on_confirm: Callable[[], Awaitable[str]],
) -> discord.Message:
    """Ask `user` to confirm something, in `channel`.

    Confirm runs `on_confirm()` and shows what it returns for a few seconds;
    Cancel, or no answer within TIMEOUT_SECONDS, removes the question and does
    nothing. Only that user can answer.
    """
    prompt = _Prompt(user, question, on_confirm)
    prompt.message = await channel.send(question, view=prompt)
    return prompt.message
