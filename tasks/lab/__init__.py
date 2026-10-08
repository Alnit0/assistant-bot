import discord

from tasks.base import Keyword, Task
from tasks.lab import common, ratelimits, state

# Importing these adds their subcommands to the /lab group
from tasks.lab import buttons, channels, charts, misc, react, status, tour  # noqa: F401  isort: skip


class LabTask(Task):
    """A test bench for Discord features: type "lab ..." (or use /lab as a fallback).

    Unlike other tasks this one uses discord.py directly: trying out what
    Discord can do is the whole point of it.
    """

    name = "lab"
    description = "Test bench for Discord features. Owner only."
    # A test bench, not something to ask Claude for: its words are typed only
    exposes_tools = False

    def keywords(self) -> list[Keyword]:
        return [
            *react.KEYWORDS,
            *buttons.KEYWORDS,
            *status.KEYWORDS,
            *charts.KEYWORDS,
            *misc.KEYWORDS,
            # Typed only: these two have no slash command
            *tour.KEYWORDS,
            *channels.KEYWORDS,
        ]

    def app_commands(self) -> list:
        return [common.lab]

    def events(self) -> dict:
        return {
            "raw_reaction_add": react.on_reaction_add,
            "raw_reaction_remove": react.on_reaction_remove,
            "guild_channel_pins_update": status.on_pins_update,
            "action_finished": tour.on_action,
        }

    def migrations(self) -> list:
        return list(state.MIGRATIONS)

    def setup(self, client: discord.Client) -> None:
        # Before connecting, so a press on an old message can never arrive too early
        buttons.register(client)
        tour.register(client)

    async def startup(self, client: discord.Client) -> None:
        ratelimits.install()
        react.bind(client)
        await status.resume(client)
        await tour.resume(client)


task = LabTask()
