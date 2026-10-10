from core.config import CHANNELS
from core import day, livelists
from tasks.base import INBOX, Keyword, Task
from tasks.pills import plain, rules, store

HUB = "hub"
# Where the words work: #inbox, and the hub once it is set in .env
WHERE = [INBOX] + ([HUB] if HUB in CHANNELS else [])


async def show_list(ctx) -> str:
    """`pills`: the list, read-only and Live. The same list as "show all my
    pills" in plain words: it is rewritten in place when a pill changes."""
    listed = await store.pills(ctx.user.id)
    message = await ctx.reply(rules.list_text(listed, day.today()))
    if message is not None:
        await livelists.placed(ctx.user.id, plain.LIST_KEY, ctx.channel_id, message.id, plain.TASK)
    return f"listed {len(rules.listed(listed))} pill(s)"


class PillsTask(Task):
    """Pills: what to take, when, and what was taken. This stage is setting them up."""

    name = "pills"
    description = "Pills: set up what you take and when, and list, pause or remove them"
    # In plain words (tasks/pills/plain.py): how the router knows this task
    icon = plain.ICON
    only_for = plain.ONLY_FOR
    examples = plain.EXAMPLES
    hint = plain.HINT
    show = "pill_list"

    def actions(self) -> list:
        return list(plain.ACTIONS)

    async def action_state(self, request):
        return await plain.state(request)

    async def already_so(self, request, about):
        return await plain.already_so(request, about)

    def keywords(self) -> list[Keyword]:
        return [
            Keyword(
                ["pills", "pill"],
                "list every pill (in use, paused, ended); to change one, say so in plain words",
                show_list,
                examples=["pills"],
                channels=WHERE,
            ),
        ]

    def migrations(self):
        return store.MIGRATIONS



task = PillsTask()
