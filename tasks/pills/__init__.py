from core.config import CHANNELS
from core import config, day, hub, livelists, tidy
from core.lifecycle import MessageClass
from core.actions import EACH_DAY
from tasks.base import INBOX, ButtonNote, Keyword, Task
from tasks.pills import checklist, plain, reminders, rules, sheet, shortcut, store
from tasks.pills import attention as pills_attention
from tasks.pills import summary as pills_summary

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


async def plan_pieces(user_id: int, on) -> list:
    """For a plan (core/planning.py): each dose with a time still to take that day, fixed. Today's are when
    each is due now (from what was taken); another day's are their planned times."""
    from core import planning
    from tasks.pills import today as pills_today

    if on == day.today():
        _, listed, _ = await checklist.read(user_id, on)
        return [
            planning.Piece("pills", f"p{dose.pill.id}.{dose.number}", plain.ICON, dose.pill.plan.name, at, fold="dose")
            for dose in listed if dose.is_pending and (at := pills_today.shown_time(dose)) is not None
        ]
    found = []
    for pill in await store.pills(user_id):
        for number, planned in pills_today.wanted(pill, on):
            if planned is not None:
                found.append(planning.Piece("pills", f"p{pill.id}.{number}", plain.ICON, pill.plan.name, day.at(on, planned), fold="dose"))
    return found


async def day_items(user_id: int, on) -> list:
    """For the hub in round 7: each of today's doses with its time and its state (taken with the time it was
    taken, skipped, missed, or still to take); one past the day's limit, never taken, is missed. Round 8 also
    draws the one Taken button on a dose that can be taken now (round 4's rule), the same as the checklist's."""
    from core import actions, clock
    from core import occurrences
    from tasks.pills import sheet
    from tasks.pills import today as pills_today

    if on != day.today():
        return []
    states = {occurrences.DONE: actions.TAKEN, occurrences.SKIPPED: actions.SKIPPED, occurrences.MISSED: actions.MISSED}
    _, listed, _ = await checklist.read(user_id, on)
    now = clock.now()
    found = []
    for dose in listed:
        state = states.get(dose.occurrence.state, actions.PENDING)
        at = dose.due.at or dose.occurrence.due_at or (day.at(on, dose.occurrence.planned_time) if dose.occurrence.planned_time else None)
        if state == actions.PENDING and at is not None and pills_today.shown_time(dose) is None:
            state = actions.MISSED  # past the day's limit: nobody could take it now
        shown = pills_today.shown_time(dose)
        can_take = state == actions.PENDING and (dose.is_untimed or (shown is not None and shown <= now))
        found.append(actions.DayItem(
            actions.DOSE, dose.pill.plan.name, at, state=state, done_at=dose.occurrence.actual_at if state == actions.TAKEN else None,
            number=dose.number, of=dose.of, button=sheet.taken_button(dose) if can_take else None,
        ))
    return found


class PillsTask(Task):
    """Pills: what to take, when, and what was taken. Setting them up, and the daily checklist."""

    name = "pills"
    place = 10  # pills, Today, reminders, personal routines, gym, calendar, diary, to-dos
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
            Keyword(
                [shortcut.WORD],
                "tick off today's next dose of that pill, as saying so would, with no wait: only the pill's exact name "
                "and nothing else; anything more is read as usual",
                shortcut.took,
                examples=["took Pill A"],
                channels=WHERE,
                takes_args=True,
                usage="<pill's exact name>",
                exact=True,
                claims=shortcut.claims,
                keep_command=True,
                purpose=EACH_DAY,
            ),
        ]

    def buttons(self) -> list[ButtonNote]:
        from core import design

        if config.CARDS_V2 and design.current() >= 4:
            # Round 4: one Taken a dose that can be taken now; Skip and a time are said in words
            return [
                ButtonNote("✅ Taken", "under a dose that can be taken now, on today's checklist and on a reminder: ticks it off at once; reply to the line it leaves with a time to put it right. To skip one, say so (“skip Pill A”), and “undo that” puts it back"),
                ButtonNote("⏰ Snooze 15m", "on a reminder: ask again in 15 minutes"),
            ]
        if config.CARDS_V2:
            # The new look: each pill on the checklist has its next dose's buttons under it
            return [
                ButtonNote("✅ Taken", "under each pill on today's checklist, and on a reminder: tick its next dose off as taken now"),
                ButtonNote("🕐 Taken at…", "under each pill on the checklist, and on a reminder: tick the dose off at a time you type"),
                ButtonNote("⏭️ Skip", "under each pill on the checklist, and on a reminder: leave that dose out today"),
                ButtonNote("⏰ Snooze 15m", "on a reminder: ask again in 15 minutes"),
            ]
        return [
            ButtonNote("✅ Taken", "under today's checklist, for a dose with no set time: tick it off as taken now"),
            ButtonNote("⏭️ Skip", "under today's checklist: leave that dose out today"),
            ButtonNote("🕐 Taken at…", "on a reminder: tick the dose off at a time you type"),
            ButtonNote("⏰ Snooze 15m", "on a reminder: ask again in 15 minutes"),
        ]

    def migrations(self):
        return store.MIGRATIONS

    async def attention(self, user_id, now):
        # Today's doses as the core's attention model sees them: due, next, or simply left
        return await pills_attention.items(user_id, now)

    def job_handlers(self):
        return {
            checklist.JOB: checklist.post_job, checklist.LIMIT_JOB: self.limit_passed, reminders.JOB: reminders.remind_job,
            history.WEEK_JOB: history.week_job,
        }

    def job_labels(self):
        # What each is called where I read it; a reminder's never names a pill
        return {
            checklist.JOB: "pills checklist", checklist.LIMIT_JOB: "pills latest-time check", reminders.JOB: "pill reminder",
            history.WEEK_JOB: history.WEEK_LABEL,
        }

    async def limit_passed(self, job):
        # A pill's latest time has passed: the checklist closes what is left, and no reminder outlives it
        await checklist.limit_job(job)
        await reminders.run()

    async def new_day(self, ended, started):
        await checklist.new_day(ended, started)
        await reminders.run()  # yesterday's reminders go, and today's first is booked

    async def channel_cleared(self, channel_id, gone):
        await checklist.channel_cleared(channel_id, gone)
        await reminders.channel_cleared(channel_id, gone)

    async def reposted(self, channel_id, gone):
        return [*await checklist.reposted(channel_id, gone), *await reminders.reposted(channel_id, gone)]

    async def message_class(self, message_id):
        kind = await store.message_kind(message_id)
        if kind is None:
            # A reminder is there to notify, and goes once it is answered
            return MessageClass.ALERT if await reminders.is_prompt(message_id) else None
        return MessageClass.LIVE if kind == store.CHECKLIST else MessageClass.ALERT

    async def owns_message(self, message_id):
        # The checklist, a dose's Taken / Skip message, and every line said about a pill or a dose
        return await self.message_class(message_id) is not None or await store.is_line(message_id)

    def setup(self, client) -> None:
        checklist.register()
        sheet.register()
        reminders.register()
        history.register()

    async def summary(self, user_id, day):
        return await pills_summary.summary(user_id, day)

    async def tally(self, user_id, day):
        return await history.tally(user_id, day)

    async def plan(self, user_id, on):
        return await plan_pieces(user_id, on)

    async def day_items(self, user_id, on):
        return await day_items(user_id, on)

    async def week(self, user_id, monday, upto):
        return await history.week_of_pills(user_id, monday, upto)

    async def startup(self, client) -> None:
        await checklist.startup()
        await reminders.startup()


task = PillsTask()
