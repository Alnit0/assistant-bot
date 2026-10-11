from core.config import CHANNELS
from core import day, hub, livelists, tidy
from core.lifecycle import MessageClass
from core.actions import EACH_DAY
from tasks.base import INBOX, ButtonNote, Keyword, Task
from tasks.pills import checklist, plain, rules, store

HUB = "hub"
# Where the words work: #inbox, and the hub once it is set in .env
WHERE = [INBOX] + ([HUB] if HUB in CHANNELS else [])


async def show_list(ctx) -> str:
    """The list of every pill, read-only and Live. The same list as "show all my
    pills" in plain words: it is rewritten in place when a pill changes."""
    listed = await store.pills(ctx.user.id)
    message = await ctx.reply(rules.list_text(listed, day.today()))
    if message is not None:
        await livelists.placed(ctx.user.id, plain.LIST_KEY, ctx.channel_id, message.id, plain.TASK)
    return f"listed {len(rules.listed(listed))} pill(s)"


async def show_today(ctx) -> str:
    """`pills`: a fresh copy of today's checklist at the bottom of the hub (here,
    if no hub is set). The old copy goes: there is only ever one for today."""
    await checklist.post(ctx.user.id, ctx.channel_id)
    where = hub.channel_id()
    if where is not None and where != ctx.channel_id:
        # Only says where to look: gone after about ten seconds
        await tidy.pointer(ctx.channel_id, plain.elsewhere_text(where))
        ctx.shown("pointed to the hub")
    return "posted today's checklist"


class PillsTask(Task):
    """Pills: what to take, when, and what was taken. Setting them up, and the daily checklist."""

    name = "pills"
    description = "Pills: today's checklist of what to take, and setting up what you take and when"
    # In plain words (tasks/pills/plain.py): how the router knows this task
    icon = plain.ICON
    only_for = plain.ONLY_FOR
    examples = plain.EXAMPLES
    identity = plain.IDENTITY
    on_repeat = plain.ON_REPEAT
    show = "pill_list"

    def actions(self) -> list:
        return list(plain.ACTIONS)

    async def action_state(self, request):
        return await plain.state(request)

    async def already_so(self, request, about):
        return await plain.already_so(request, about)

    async def item_names(self, request):
        return await plain.names(request)

    def keywords(self) -> list[Keyword]:
        return [
            Keyword(
                ["pills", "pill"],
                "today's checklist, fresh at the bottom of the hub; \"my pills\" lists every pill, and to change one, say so in plain words",
                show_today,
                examples=["pills"],
                channels=WHERE,
                purpose=EACH_DAY,
            ),
        ]

    def buttons(self) -> list[ButtonNote]:
        return [
            ButtonNote("✅ Taken", "under today's checklist, for a dose with no set time: tick it off as taken now"),
            ButtonNote("⏭️ Skip", "under today's checklist: leave that dose out today"),
        ]

    def migrations(self):
        return store.MIGRATIONS

    def job_handlers(self):
        return {checklist.JOB: checklist.post_job, checklist.LIMIT_JOB: checklist.limit_job}

    async def new_day(self, ended, started):
        await checklist.new_day(ended, started)

    async def channel_cleared(self, channel_id, gone):
        await checklist.channel_cleared(channel_id, gone)

    async def reposted(self, channel_id, gone):
        return await checklist.reposted(channel_id, gone)

    async def message_class(self, message_id):
        kind = await store.message_kind(message_id)
        if kind is None:
            return None
        return MessageClass.LIVE if kind == store.CHECKLIST else MessageClass.ALERT

    def setup(self, client) -> None:
        checklist.register()

    async def startup(self, client) -> None:
        await checklist.startup()


task = PillsTask()
