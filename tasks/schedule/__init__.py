from core import livelists, repeats
from core.actions import ADD, ITEMS, LIST, REMOVE, SEE, SET, SET_UP, TIME, Action, Field
from core.config import CHANNELS
from core.context import Context
from core.timetable import NOTIFY, SILENT
from tasks.base import ANY, Keyword, Task
from tasks.schedule import plain
from tasks.schedule.rules import DAY_WORDS, ICON, PAUSE, RESUME, TASK

# ---------------------------------------------------------------------------
# Schedule: when the bot does things by itself, seen and changed in plain
# words. The rows and the engine are the core's (core/timetable.py,
# core/scheduler.py), as pinning is core/pins.py's: this task is only the
# conversation, so that the router finds it in the registry and core never
# imports a task.
#
#   my schedule                          the list, kept up to date in place
#   "move the pills checklist to 7"      a change card: time · 6:00 am → 7:00 am
#   "pause it until Monday"              paused · no → until Mon 19 Oct
#   "also post the checklist at 6 pm"    a new schedule for a handler that exists
#   "remove the evening one"             a remove card
# ---------------------------------------------------------------------------
ONLY_FOR = (
    "When the bot posts or does things by itself, and changing that: the time of day it posts something (the pills "
    "checklist, a briefing, a routine), the days of the week, pausing one or turning it back on, silent or with a "
    "notification, which channel, adding another time for one, removing one, and asking what is scheduled. Not the "
    "times a pill is taken (that is the pills task, even when the message says \"move\"), not timers, and not a "
    "reminder to do something."
)
EXAMPLES = ("what's on my schedule?", "move the pills checklist to 7", "pause the checklist until Monday")
WHERE = ANY

_WHICH = (
    "Which schedule, exactly as the user said it (a name or part of one from the state). Never complete or correct "
    "it: the code finds which is meant, and asks when more than one fits."
)
_CHANGE_FIELDS = (
    Field("schedule", _WHICH, required=True),
    Field("time", "The new time of day, if the user gave one.", TIME),
    Field(
        "days",
        "The days of the week the user named, if any: \"weekdays\" is mon tue wed thu fri, \"weekends\" is sat sun, "
        "\"every day\" is all seven. Only the days named.",
        LIST,
        choices=DAY_WORDS,
    ),
    Field(
        "days_change",
        "What to do with those days. set: these are the days it runs on (\"weekdays only\", \"on Mondays\", \"every "
        "day\"). add: these as well (\"also Saturdays\"). remove: not on these (\"not on Sundays\"). Leave out for set.",
        choices=(ADD, SET, REMOVE),
    ),
    Field("notify", "silent: post without a notification. notify: with one. Only if the user asked.", choices=(SILENT, NOTIFY)),
    Field("paused", "pause: stop it for now. resume: turn it back on. Only if the user asked.", choices=(PAUSE, RESUME)),
    Field("until", "For a pause with an end: the day it is on again, exactly as the user said it (Monday, the 20th). Never work out a date."),
    Field("channel", "The channel to post in, if the user named one.", choices=tuple(sorted(CHANNELS))),
)


async def show_word(ctx: Context) -> str:
    """`my schedule`: the list, as the Live copy."""
    shown = await plain.list_card()
    await livelists.show(ctx.user.id, plain.KEY, ctx.channel_id, shown, task=TASK)
    return "shown"


class ScheduleTask(Task):
    """My schedule: what the bot does by itself and when, and changing it by words."""

    name = TASK
    description = "Schedule: when the bot posts things by itself, and changing that by words"
    icon = ICON
    only_for = ONLY_FOR
    examples = EXAMPLES
    show = "schedule_show"
    # Two schedules are the same when they run the same thing at the same time
    identity = ("what", "time")
    on_repeat = repeats.SHOW_EXISTING

    def setup(self, client) -> None:
        plain.register()  # Undo under a change's "Saved"

    async def action_state(self, request):
        return await plain.state(request)

    async def item_names(self, request):
        return await plain.item_names(request)

    def actions(self) -> list:
        return [
            Action(
                "schedule_show",
                "The user asks what is scheduled, or when the bot posts things (\"what's on my schedule?\", \"when do you post the checklist?\").",
                needs_card=False,
                run=plain.show,
                purpose=SEE,
                say=("what's on my schedule?",),
            ),
            Action(
                "schedule_change",
                "Change one or more schedules that exist: the time, the days, pause or resume, silent or notify, the channel. "
                "Examples: \"move the pills checklist to 7\" -> schedule pills checklist, time 7:00 am (your best reading, "
                "listed as guessed if it could be evening). \"checklist on weekdays only\" -> days mon tue wed thu fri, "
                "days_change set. \"not on Sundays\" -> days sun, days_change remove. \"pause the checklist until Monday\" -> "
                "paused pause, until Monday. \"turn it back on\" -> paused resume. \"make it silent\" -> notify silent. "
                "For one of the bot's own (the nightly backup, the end of the day) fill the change in all the same: the "
                "bot's code answers that it is not changed here. Never decline because of whose it is.",
                (Field("schedules", "Each schedule the message changes, one item each.", ITEMS, required=True, item_fields=_CHANGE_FIELDS),),
                prepare=plain.change_card,
                apply=plain.change_save,
                verify=plain.change_check,
                purpose=SET_UP,
                say=("move the pills checklist to 7",),
            ),
            Action(
                "schedule_add",
                "Add another schedule for something the bot can post by itself (see \"Can be scheduled\" in the state): "
                "\"also post the pills checklist at 6 pm\" -> what pills checklist, time 6:00 pm. For changing one that "
                "exists, use the change action.",
                (
                    Field("what", "What to schedule, exactly as the user said it.", required=True),
                    Field("time", "The time of day, if the user gave one. Leave out if not: the card asks.", TIME),
                    Field("days", "The days of the week, if the user named any. Leave out for every day.", LIST, choices=DAY_WORDS),
                    Field("notify", "silent or notify, only if the user asked.", choices=(SILENT, NOTIFY)),
                    Field("channel", "The channel to post in, if the user named one.", choices=tuple(sorted(CHANNELS))),
                ),
                prepare=plain.add_card,
                apply=plain.add_save,
                verify=plain.add_check,
                purpose=SET_UP,
                say=("also post the pills checklist at 6 pm",),
            ),
            Action(
                "schedule_remove",
                "Remove one or more schedules, so the bot stops doing that by itself (\"remove the evening checklist\", "
                "\"stop posting the checklist\"). To stop one for a while, use the change action with pause.",
                (Field("schedules", "Each schedule to remove, one item each.", ITEMS, required=True, item_fields=(Field("schedule", _WHICH, required=True),)),),
                prepare=plain.remove_card,
                apply=plain.remove_save,
                verify=plain.remove_check,
                purpose=SET_UP,
                say=("remove the evening checklist",),
            ),
        ]

    def keywords(self) -> list[Keyword]:
        return [
            Keyword(
                ["my schedule", "schedule"],
                "what the bot does by itself and when: each schedule, where it posts, its next and last run. Change one by "
                "saying so (\"move the pills checklist to 7\")",
                show_word,
                examples=["my schedule"],
                channels=WHERE,
                exact=True,
                keep_command=True,
                purpose=SEE,
            ),
        ]


task = ScheduleTask()
