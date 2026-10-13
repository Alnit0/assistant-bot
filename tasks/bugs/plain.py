from core.actions import EACH_DAY, SEE, Action, Field, LiveReply, Request
from core.errors import UserError
from tasks.bugs import filing, listing, posts, rules, store

# ---------------------------------------------------------------------------
# Bugs in plain words (core/actions.py): "that's a bug", "show my open bugs".
# Reporting logs something and changes no setup, so neither needs a card.
# ---------------------------------------------------------------------------
async def report_said(request: Request, data: dict, guessed: frozenset) -> str:
    """Report the message replied to, or else the user's own newest message
    before this one (never one of the bot's: the report is about that turn).
    What they said was wrong, if they typed it, is kept as the bug's first note."""
    if request.replied_to is not None:
        target, source = await posts.fetch_message(request.channel_id, request.replied_to), rules.REPLY
    else:
        target, source = await posts.latest_before(request.channel_id, request.message_id), rules.WORD
    rules.check_reportable(target)
    already = await store.open_for(request.user.id, target.channel.id, target.id)
    before = await posts.preceding(target)
    text = await filing.file_report(request.user, target.channel.id, rules.snapshot(target), before, source, request.message_id)
    note = (data.get("note") or "").strip()
    item = await store.open_for(request.user.id, target.channel.id, target.id)
    if note and item is not None:
        # Said to be saved only once it has been read back
        if not await filing.add_note(item.id, request.user.id, note, request.message_id):
            raise UserError(f"{text} · but your note didn't save. Write it in the bug's post.")
        text += " · 📝 your note is saved with it" if already is None else " · 📝 note added"
    return text


async def list_said(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    """The open bugs, as the word `bugs` shows them: Live, kept up to date in place."""
    shown = await listing.card(request.user.id)
    return LiveReply(listing.KEY, shown.text, shown)


ACTIONS = (
    Action(
        "bug_report",
        "The user says the bot itself got something wrong and wants it logged as a bug: \"that's a bug\", "
        "\"log that as a bug\", \"bug: it started two timers\" -> note \"it started two timers\". Only when "
        "they say bug or report. A correction of what they asked for (\"no, I meant 5 minutes\") is not "
        "a bug report: call `none`.",
        (
            Field(
                "note",
                "What the user said was wrong, in their words, if they said. Leave out if they only said it is a bug.",
            ),
        ),
        needs_card=False,
        run=report_said,
        purpose=EACH_DAY,
        say=("that's a bug: it started two timers",),
    ),
    Action(
        "bug_list",
        "The user asks which bugs are open (\"show my open bugs\", \"what bugs have I reported?\").",
        needs_card=False,
        run=list_said,
        purpose=SEE,
        say=("show my open bugs",),
    ),
)
