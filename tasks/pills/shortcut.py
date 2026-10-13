from core import actions, confirm, llm, messages, names
from core.actions import Answer, Request
from core.context import Context
from tasks.pills import checklist, rules, today
from tasks.pills.today import TASK

# ---------------------------------------------------------------------------
# Pills: the one typed shortcut for logging, "took <pill>".
#
# It is a shortcut only when what follows "took" is exactly the name of one of
# my pills, with nothing else, and that pill has a dose still to take today
# or one that was missed (`claims`). Anything more ("took my zinc", "took zinc at 9") is not it, and
# goes to the router and Claude as it always did. Asked for on 2026-10-13: it
# was nine of the twenty-four messages that went through the router.
#
# What it does is what saying it does, by the same code (the `pill_log`
# action): the next dose is ticked off now, and one that would be too soon or
# too late is asked about first on a card. No request to Claude is made.
# ---------------------------------------------------------------------------
WORD = "took"


def named(ctx_args: list[str]) -> str:
    return names.tidy(" ".join(ctx_args))


async def claims(ctx: Context, args: list[str]) -> bool:
    """Whether "took …" is the shortcut: the rest is the whole name of exactly
    one of my pills, and it has a dose still to take today."""
    wanted = named(args)
    if not wanted:
        return False
    pills, listed, _ = await checklist.view(ctx.user.id)
    exact = [pill for pill in rules.listed(pills) if names.tidy(pill.plan.name) == wanted]
    # A dose that was missed counts: it can still be logged, and the card asks first
    return len(exact) == 1 and today.next_to_log(listed, exact[0].id) is not None


async def took(ctx: Context) -> str:
    """Tick the pill's next dose off as taken now, as saying it would."""
    request = Request(ctx.user, ctx.channel_id, ctx.text, message_id=ctx.message_id)
    data = {"doses": [{"pill": " ".join(ctx.args), "did": checklist.TAKEN}]}
    entry = actions.entry(TASK)
    action = entry.action("pill_log")
    if await action.card_if(request, data, frozenset()):
        # Too soon, or after the latest time: asked first, as when it is said
        await confirm.show(request, entry, action.name, await action.prepare(request, data, frozenset()), frozenset())
        ctx.shown("asked first on a card")
        return "asked first on a card"
    result = await action.run(request, data, frozenset())
    said = result.text if isinstance(result, Answer) else str(result)
    message = await ctx.reply(said)
    if isinstance(result, Answer) and message is not None:
        # The line is that pill's and that dose's: a reply to it means them
        await result.placed(message.id)
    if message is not None and not messages.in_hub(ctx.channel_id):
        # A line that reports a change lasts the day (with the tidy on); in the hub it goes with what I typed
        await messages.record(message.id, ctx.channel_id, lifetime=messages.DAY, task=TASK)
    # So that the next message isn't answered as if this were still waiting
    llm.remember(ctx.channel_id, ctx.text, said)
    llm.task_answered(ctx.channel_id, TASK)
    return said
