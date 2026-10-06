import discord

from skills.base import Reaction, Skill
from skills.lab import common, ratelimits, state

# Importing these adds their subcommands to the /lab group
from skills.lab import archive, buttons, charts, misc, react, status  # noqa: F401  isort: skip


class LabSkill(Skill):
    """A test bench for Discord features, behind the /lab slash commands.

    Unlike other skills this one uses discord.py directly: trying out what
    Discord can do is the whole point of it.
    """

    name = "lab"
    description = "Test bench for Discord features (/lab slash commands)"

    def app_commands(self) -> list:
        return [common.lab, archive.archive_menu]

    def reactions(self) -> list[Reaction]:
        return [Reaction(archive.ARCHIVE_EMOJI, archive.on_archive_reaction)]

    def events(self) -> dict:
        return {
            "app_command_completion": common.finish,
            "app_command_error": common.fail,
            "raw_reaction_add": react.on_reaction_add,
            "raw_reaction_remove": react.on_reaction_remove,
            "guild_channel_pins_update": status.on_pins_update,
        }

    def migrations(self) -> list:
        return list(state.MIGRATIONS)

    async def startup(self, client: discord.Client) -> None:
        ratelimits.install()
        react.bind(client)
        archive.bind(client)
        buttons.register(client)
        await status.resume(client)


skill = LabSkill()
