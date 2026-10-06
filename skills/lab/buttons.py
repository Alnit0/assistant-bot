import logging
import re

import discord

from skills.lab.common import (
    STARTED_AT,
    Run,
    SlashRun,
    check_owner,
    lab,
    lab_keyword,
    record_press,
    report_component_error,
)

log = logging.getLogger("assistant")

DEMO_TIMEOUT = 900  # seconds before the interactive message stops responding
DOCS_URL = "https://discordpy.readthedocs.io/en/stable/interactions/api.html"


def _on_off(value: bool) -> str:
    return "on" if value else "off"


# ---------------------------------------------------------------------------
# Modal form
# ---------------------------------------------------------------------------
class LabForm(discord.ui.Modal, title="Lab form"):
    name = discord.ui.TextInput(
        label="Name", placeholder="A short piece of text", max_length=50
    )
    notes = discord.ui.TextInput(
        label="Notes",
        style=discord.TextStyle.paragraph,
        placeholder="A longer, optional piece of text",
        required=False,
        max_length=500,
    )

    def __init__(self, demo: "DemoView"):
        super().__init__()
        self.demo = demo

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_component_error(interaction, error, "buttons: form")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await check_owner(interaction):
            return
        self.demo.form = (self.name.value, self.notes.value)
        await interaction.response.edit_message(content=self.demo.render(), view=self.demo)
        await record_press(
            interaction,
            "buttons: form submitted",
            f"name: {self.name.value}; notes: {self.notes.value or '(none)'}",
        )


# ---------------------------------------------------------------------------
# Interactive message: state lives in memory, so it stops working at restart
# ---------------------------------------------------------------------------
class DemoView(discord.ui.View):
    """Counter, toggles, selects, a form, an ephemeral reply and a link button."""

    def __init__(self):
        super().__init__(timeout=DEMO_TIMEOUT)
        self.message: discord.Message | None = None
        self.count = 0
        self.alerts = False
        self.quiet_hours = False
        self.urgency: str | None = None
        self.topics: list[str] = []
        self.form: tuple[str, str] | None = None
        # A link button has no callback: Discord opens the URL itself
        self.add_item(discord.ui.Button(label="Docs", emoji="🔗", url=DOCS_URL, row=4))

    def render(self) -> str:
        lines = [
            "🧪 **Component test** (this text is edited in place)",
            f"Count: **{self.count}** · Alerts: **{_on_off(self.alerts)}** · "
            f"Quiet hours: **{_on_off(self.quiet_hours)}**",
            f"Urgency: **{self.urgency or 'not chosen'}** · "
            f"Topics: **{', '.join(self.topics) or 'none'}**",
        ]
        if self.form:
            name, notes = self.form
            lines.append(f"Form: **{name}**" + (f"\n> {notes}" if notes else ""))
        else:
            lines.append("Form: not submitted")
        return "\n".join(lines)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await check_owner(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        await report_component_error(interaction, error, "buttons: component test")

    async def refresh(self, interaction: discord.Interaction, label: str, summary: str) -> None:
        await interaction.response.edit_message(content=self.render(), view=self)
        await record_press(interaction, f"buttons: {label}", summary)

    @discord.ui.button(label="Count: 0", style=discord.ButtonStyle.primary, row=0)
    async def counter(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.count += 1
        button.label = f"Count: {self.count}"
        await self.refresh(interaction, "counter", f"count is now {self.count}")

    @discord.ui.button(label="Reset", style=discord.ButtonStyle.secondary, row=0)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.count = 0
        self.counter.label = "Count: 0"
        await self.refresh(interaction, "reset", "count reset to 0")

    @discord.ui.button(label="Alerts: off", emoji="🔔", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_alerts(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.alerts = not self.alerts
        button.label = f"Alerts: {_on_off(self.alerts)}"
        button.style = discord.ButtonStyle.success if self.alerts else discord.ButtonStyle.secondary
        await self.refresh(interaction, "alerts toggle", f"alerts {_on_off(self.alerts)}")

    @discord.ui.button(label="Quiet hours: off", emoji="🌙", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_quiet(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.quiet_hours = not self.quiet_hours
        button.label = f"Quiet hours: {_on_off(self.quiet_hours)}"
        button.style = (
            discord.ButtonStyle.success if self.quiet_hours else discord.ButtonStyle.secondary
        )
        await self.refresh(interaction, "quiet hours toggle", f"quiet hours {_on_off(self.quiet_hours)}")

    @discord.ui.select(
        placeholder="Urgency (pick one)",
        row=2,
        options=[
            discord.SelectOption(label="Low", emoji="🟢"),
            discord.SelectOption(label="Normal", emoji="🟡"),
            discord.SelectOption(label="High", emoji="🔴"),
        ],
    )
    async def pick_urgency(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.urgency = select.values[0]
        # Mark the choice as the default, or the menu looks empty again after the edit
        for option in select.options:
            option.default = option.value in select.values
        await self.refresh(interaction, "single select", f"urgency: {self.urgency}")

    @discord.ui.select(
        placeholder="Topics (pick any number)",
        min_values=0,
        max_values=4,
        row=3,
        options=[
            discord.SelectOption(label="Reminders", emoji="⏰"),
            discord.SelectOption(label="Gym", emoji="🏋️"),
            discord.SelectOption(label="Documents", emoji="📄"),
            discord.SelectOption(label="Journal", emoji="📓"),
        ],
    )
    async def pick_topics(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.topics = list(select.values)
        for option in select.options:
            option.default = option.value in select.values
        await self.refresh(interaction, "multi select", f"topics: {', '.join(self.topics) or 'none'}")

    @discord.ui.button(label="Form", emoji="📝", style=discord.ButtonStyle.secondary, row=4)
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LabForm(self))
        await record_press(interaction, "buttons: form opened", "showed the modal form")

    @discord.ui.button(label="Ephemeral", emoji="🙈", style=discord.ButtonStyle.secondary, row=4)
    async def ephemeral(self, interaction: discord.Interaction, button: discord.ui.Button):
        reply = "🙈 Only you can see this, and you can dismiss it."
        await interaction.response.send_message(reply, ephemeral=True)
        await record_press(interaction, "buttons: ephemeral", reply)

    async def on_timeout(self) -> None:
        for item in self.children:
            # Link buttons keep working: they never reach the bot
            if not getattr(item, "url", None):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(content=self.render() + "\n⌛ Expired.", view=self)
            except discord.HTTPException:
                pass


# ---------------------------------------------------------------------------
# Persistent buttons: found again by custom_id, so they survive a restart
# ---------------------------------------------------------------------------
class PersistentPanel(discord.ui.View):
    """A fixed custom_id. Registered with the client at startup, with no timeout."""

    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await check_owner(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        await report_component_error(interaction, error, "buttons: persistent panel")

    @discord.ui.button(
        label="Uptime", emoji="🕒", style=discord.ButtonStyle.secondary, custom_id="lab:uptime"
    )
    async def uptime(self, interaction: discord.Interaction, button: discord.ui.Button):
        started = int(STARTED_AT.timestamp())
        reply = (
            f"🕒 This copy of the bot started <t:{started}:R> (<t:{started}:T>). "
            "If this button's message is older than that, it survived a restart."
        )
        await interaction.response.send_message(reply, ephemeral=True)
        await record_press(interaction, "buttons: persistent uptime", reply)


class VoteButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"lab:vote:(?P<count>\d+)"
):
    """A counter whose value is stored in its own custom_id, so nothing is kept in memory."""

    def __init__(self, count: int = 0):
        super().__init__(
            discord.ui.Button(
                label=f"Votes: {count}",
                emoji="👍",
                style=discord.ButtonStyle.primary,
                custom_id=f"lab:vote:{count}",
            )
        )
        self.count = count

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ):
        return cls(int(match["count"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # discord.py treats an error in a dynamic item's check as a silent "no"
        try:
            return await check_owner(interaction)
        except Exception as error:
            await report_component_error(interaction, error, "buttons: persistent vote")
            return False

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            count = self.count + 1
            # Send back a complete, freshly built panel. self.view is discord.py's
            # bare copy of the message: its other buttons have no handlers, and
            # passing it back would make them the ones registered for this message
            await interaction.response.edit_message(view=build_panel(count))
            await record_press(interaction, "buttons: persistent vote", f"votes: {count}")
        except Exception as error:
            await report_component_error(interaction, error, "buttons: persistent vote")


def build_panel(votes: int = 0) -> PersistentPanel:
    """The persistent message's buttons, with every handler attached."""
    panel = PersistentPanel()
    panel.add_item(VoteButton(votes))
    return panel


def register(client: discord.Client) -> None:
    """Tell the client about the persistent buttons, so old messages keep working.

    Must run before the bot connects, so no press can arrive unregistered.
    """
    client.add_view(PersistentPanel())
    client.add_dynamic_items(VoteButton)
    log.info("Registered persistent lab buttons: lab:uptime, lab:vote:<n>")


async def run_buttons(run: Run) -> None:
    await run.start()
    demo = DemoView()
    demo.message = await run.channel.send(demo.render(), view=demo)

    await run.channel.send(
        "♾️ **Persistent buttons**\nRestart the bot, then press these again: they still work.",
        view=build_panel(),
    )

    run.note("posted the component test and the persistent buttons")
    await run.done("Component tests posted.")


@lab.command(name="buttons", description="Buttons, selects, a form, and buttons that survive restarts")
async def buttons(interaction: discord.Interaction):
    await run_buttons(SlashRun(interaction))


KEYWORDS = [
    lab_keyword(
        "lab buttons",
        "buttons, selects, a form, and buttons that survive restarts",
        run_buttons,
    ),
]
