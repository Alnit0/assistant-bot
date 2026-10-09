from core.config import CHANNELS
from core.lifecycle import MessageClass
from tasks.base import INBOX, Keyword, Param, Task, Tool
from tasks.pills import plans, store

HUB = "hub"
# Where the words work: #inbox, and the hub once it is set in .env
WHERE = [INBOX] + ([HUB] if HUB in CHANNELS else [])

# How Claude is to hand over what the user said, the same for every tool
AS_SAID = (
    "Pass times and dates exactly as the user said them (8, 8pm, 20:00, tomorrow, the 20th): never convert "
    "them, never add am or pm, never work out a date. The code reads them and asks the user if one is unclear."
)

_PLAN_PARAMS = [
    Param("dose", "How much each time, e.g. 1 tablet.", required=False),
    Param("notes", "Instructions, e.g. with food.", required=False),
    Param(
        "times",
        "The time of each dose as the user said it, separated by commas, e.g. `8am, 8pm` or `20:00`. "
        "With min_gap, at most one: the time of the first dose.",
        required=False,
    ),
    Param("per_day", "How many doses a day, as a number, e.g. 3. Not needed when times are given.", required=False),
    Param(
        "min_gap",
        "The minimum time between doses, with its unit, e.g. 3h or 90m. Only for a pill taken several times "
        "a day at least so long apart.",
        required=False,
    ),
    Param("start", "For a course only: its first day as the user said it, e.g. tomorrow.", required=False),
    Param("end", "For a course only: its last day as the user said it, e.g. the 16th.", required=False),
    Param("days", "For a course only: how many days it lasts, as a number, in place of end.", required=False),
]


class PillsTask(Task):
    """Pills: what to take, when, and what was taken. This stage is setting them up."""

    name = "pills"
    description = "Pills: set up what you take and when, and list, pause or remove them"

    def keywords(self) -> list[Keyword]:
        return [
            Keyword(
                ["pills", "pill"],
                "list every pill (in use, paused, ended), with a dropdown to edit, pause or remove one",
                plans.show_list,
                examples=["pills"],
                channels=WHERE,
            ),
        ]

    def tools(self) -> list[Tool]:
        return [
            Tool(
                "pill_add",
                "Set up a new pill (or vitamin, medicine, supplement) the user takes. It saves NOTHING: it "
                "shows the user a preview with Save and Edit buttons, and only their Save adds it, so never "
                "say it has been added. Examples: \"add vitamin D, once a day\" -> name Vitamin D. \"add "
                "evening pill at 20:00\" -> name Evening pill, times 20:00. \"add course A, 3 times a day, at "
                "least 3 hours apart, with food, for 7 days starting tomorrow\" -> name Course A, per_day 3, "
                "min_gap 3h, notes with food, start tomorrow, days 7. A pill with no end has no dates: leave "
                "start, end and days empty and don't ask for them. To change a preview that is still open "
                f"(listed in the live state), call this again with its draft id and only what changes. {AS_SAID}",
                plans.add_tool,
                params=[
                    Param("name", "What the pill is called, e.g. Vitamin D. May be empty when changing a draft.", required=False),
                    *_PLAN_PARAMS,
                    Param("draft", "The id of an open preview to change (d5), from the live state.", required=False),
                ],
                channels=WHERE,
                tool_priority=6,
            ),
            Tool(
                "pill_edit",
                "Change a pill the user already has: its name, dose, notes, times, how often, the gap, or its "
                "dates. It changes NOTHING by itself: it shows a preview of the old and new plan with Save and "
                "Edit buttons, and only the user's Save applies it. Give only what changes; everything else "
                "stays. To take something away, give `none` for it (notes none; times none makes it untimed; "
                "end none makes it go on with no end). Examples: \"move the evening pill to 9pm\" -> pill "
                "Evening pill, times 9pm. \"vitamin D is 2 tablets now\" -> dose 2 tablets. If a preview for "
                f"that pill is already open, this changes that preview. {AS_SAID}",
                plans.edit_tool,
                params=[
                    Param("pill", "Which pill: its id from the live state (pl3) or its name."),
                    Param("name", "A new name for it.", required=False),
                    *_PLAN_PARAMS,
                ],
                channels=WHERE,
                tool_priority=5,
            ),
            Tool(
                "pill_pause",
                "Pause a pill (it stops being asked for, and its streak is unaffected) or resume one. Acts at "
                "once. Examples: \"pause iron\" -> action pause. \"pause iron until the 20th\" -> until the "
                "20th (the day it is taken again). \"start iron again\" -> action resume. " + AS_SAID,
                plans.pause_tool,
                params=[
                    Param("pill", "Which pill: its id from the live state (pl3) or its name."),
                    Param("action", "pause or resume.", choices=("pause", "resume")),
                    Param("until", "For pause: the day it is taken again, as the user said it. Empty for no end.", required=False),
                ],
                channels=WHERE,
                tool_priority=4,
            ),
            Tool(
                "pill_remove",
                "Remove a pill the user no longer takes. The user is asked to confirm with buttons first, so "
                "never say it is done. Normally its history is kept (history keep). Use history delete ONLY "
                "when the user explicitly asks to delete the pill together with its history or records "
                "(\"delete iron and its history\"); that cannot be undone.",
                plans.remove_tool,
                params=[
                    Param("pill", "Which pill: its id from the live state (pl3) or its name."),
                    Param("history", "keep (the default) or delete.", choices=("keep", "delete")),
                ],
                channels=WHERE,
                tool_priority=3,
            ),
        ]

    async def live_state(self, ctx) -> str:
        return await plans.live_state(ctx)

    def job_handlers(self):
        return {plans.JOB_DRAFT: plans.draft_expired}

    def migrations(self):
        return store.MIGRATIONS

    async def message_class(self, message_id: int) -> MessageClass | None:
        return await plans.message_class(message_id)

    def setup(self, client) -> None:
        plans.register_actions()


task = PillsTask()
