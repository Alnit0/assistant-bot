import discord

from skills.base import Skill
from skills.lab import common, ratelimits

# Importing these adds their subcommands to the /lab group
from skills.lab import misc  # noqa: F401  isort: skip


class LabSkill(Skill):
    """A test bench for Discord features, behind the /lab slash commands.

    Unlike other skills this one uses discord.py directly: trying out what
    Discord can do is the whole point of it.
    """

    name = "lab"
    description = "Test bench for Discord features (/lab slash commands)"

    def app_commands(self) -> list:
        return [common.lab]

    def events(self) -> dict:
        return {
            "app_command_completion": common.finish,
            "app_command_error": common.fail,
        }

    async def startup(self, client: discord.Client) -> None:
        ratelimits.install()


skill = LabSkill()
