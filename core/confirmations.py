import logging
from collections.abc import Awaitable, Callable

import discord

from core import lifecycle
from core.config import CONFIRMATION_SECONDS
from core.database import log_received, log_result
from core.discord_utils import log_error, report_interaction_error, safe_reply
from core.errors import UserError
from core.lifecycle import MessageClass
from core.users import User, get_user_by_discord_id

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Confirmations: buttons under a short message of the bot's.
#   ask         "are you sure?" before something that can't easily be undone
#   choose      "which one?" when more than one thing could be meant
#   offer_undo  "done", with a way to take it back for a little while
#
# All are held in memory. One left unanswered times out and removes itself;
# one caught by a restart stops working (the user is told so if they press it).
# ---------------------------------------------------------------------------
TIMEOUT_SECONDS = 120
UNDO_SECONDS = 30
MAX_CHOICES = 5


class _OwnedView(discord.ui.View):
    """Buttons only one user may press, on a message that tidies itself away."""

    def __init__(self, user: User, timeout: float):
        super().__init__(timeout=timeout)
        self.user = user
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
                if lifecycle.deletes(MessageClass.TRANSIENT):
                    await self.message.delete()
                else:
                    # Clean-up is off: leave the message, without its buttons
                    await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    async def on_timeout(self) -> None:
        await self._remove()

    async def _finish(self, interaction: discord.Interaction, what: str, action: Callable[[], Awaitable[str]]) -> None:
        """Run what a button stands for, then show how it went in place of the buttons."""
        # Answer first; the action itself may take a moment
        await interaction.response.defer()
        self.stop()
        row_id = await log_received(
            what, "confirmation", interaction.message.id, interaction.channel_id, user_id=self.user.id
        )
        try:
            outcome = await action()
        except UserError as error:
            await log_result(row_id, status="error", error=str(error))
            await log_error("Confirmed action failed", str(error), what)
            await interaction.message.edit(
                content=f"⚠️ {error}", view=None, delete_after=lifecycle.delete_after(CONFIRMATION_SECONDS * 3)
            )
            return
        await log_result(row_id, reply=outcome, status="ok")
        await interaction.message.edit(content=outcome, view=None, delete_after=lifecycle.delete_after())


class _Prompt(_OwnedView):
    def __init__(self, user: User, question: str, on_confirm: Callable[[], Awaitable[str]]):
        super().__init__(user, TIMEOUT_SECONDS)
        self.question = question
        self.on_confirm = on_confirm

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, f"confirmed: {self.question}", self.on_confirm)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
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


class _Choice(_OwnedView):
    def __init__(self, user: User, question: str, options: list[tuple[str, Callable[[], Awaitable[str]]]]):
        super().__init__(user, TIMEOUT_SECONDS)
        for label, on_pick in options[:MAX_CHOICES]:
            self.add_item(self._button(question, label, on_pick))
        cancel = discord.ui.Button(label="None of these", style=discord.ButtonStyle.secondary)
        cancel.callback = self._cancel
        self.add_item(cancel)

    def _button(self, question: str, label: str, on_pick: Callable[[], Awaitable[str]]) -> discord.ui.Button:
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)

        async def pressed(interaction: discord.Interaction) -> None:
            await self._finish(interaction, f"chose {label}: {question}", on_pick)

        button.callback = pressed
        return button

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self._remove()


async def choose(
    channel: discord.abc.Messageable,
    user: User,
    question: str,
    options: list[tuple[str, Callable[[], Awaitable[str]]]],
) -> discord.Message:
    """Ask `user` which of a few things they mean: one button each, plus "None of these".

    `options` is (button label, what to run). Pressing one runs it and shows
    what it returns; no answer within TIMEOUT_SECONDS removes the question.
    """
    view = _Choice(user, question, options)
    view.message = await channel.send(question, view=view)
    return view.message


class _Undo(_OwnedView):
    def __init__(self, user: User, text: str, on_undo: Callable[[], Awaitable[str]], seconds: float):
        super().__init__(user, seconds)
        self.text = text
        self.on_undo = on_undo

    @discord.ui.button(label="Undo", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def undo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, f"undo: {self.text}", self.on_undo)


async def offer_undo(
    channel: discord.abc.Messageable,
    user: User,
    text: str,
    on_undo: Callable[[], Awaitable[str]],
    seconds: float = UNDO_SECONDS,
) -> discord.Message:
    """Say that something was done, with an Undo button for `seconds`.

    Undo runs `on_undo()` and shows what it returns. Either way the message
    is a passing confirmation and removes itself.
    """
    view = _Undo(user, text, on_undo, seconds)
    view.message = await channel.send(text, view=view)
    lifecycle.note_transient(view.message.id)
    return view.message
