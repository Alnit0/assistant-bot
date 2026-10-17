import logging
from datetime import date, timedelta

from core import cards, clock, config, database, hub, messages, notify, scheduler, summaries, timeinput
from core.actions import BOOLEAN, Field, Proposal, Request, Shown, State
from core.attention import TIMED, Item
from core.cards import Button, Card
from core.errors import UserError
from tasks.diary import mood, rules, store
from tasks.diary.rules import ICON, TASK, Entry

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The diary in plain words, the mood buttons, and the evening ask.
#
# Claude decides that a message is a diary entry (the router) and, if the words
# make it clear, which mood (extraction): nothing else. Python keeps the words
# exactly as sent, in the database and nowhere else; every line said back names
# none of them. The core is told the words are private (Entry.private), so the
# message log, #bot-log and the router's memory keep a note in their place.
# ---------------------------------------------------------------------------
MOOD, UNDO = "mood", "undo"
WRITE, WRITTEN = "write", "written"  # the ✍️ Write button and what its form sends back
WRITE_LABEL, ADD_LABEL = "Write", "Add a few words"
FORM_TITLE = "How was today?"
KIND = "diary.ask"  # the evening ask: Discord only, never ntfy, held back in quiet hours (core/notify.py)
ASK_JOB = "ask"
TODAY_JOB = "today"  # 6 pm: the Today card drawn again, for its evening line
NOT_SAVED = "That didn't save: nothing was written to the diary. Try again in a moment."

ONLY_FOR = (
    "The user's own diary: their words about how their day went or how they feel, to keep (\"today was good, finally "
    "finished the essay\", \"rough day, work ran late\", \"add to today's diary: …\"), the mood of a day (\"actually today "
    "was ok\"), reading back what they wrote or how their mood went (\"what did I write last Tuesday?\", \"show this "
    "week's diary\", \"how was my mood this month?\"), and deleting a day's entry. With the diary here, words "
    "about the user's own day or how they feel (\"rough day, work ran late\", \"dear diary, …\", \"actually today was ok\" "
    "after an entry) are its, never a remark to pass over. Not a pill, to-do, routine or reminder "
    "done (those tasks), not a question about the day's plan (the briefing), and not a remark to the bot."
)
# Question 85 (Alex, 15 Oct: yes): with the diary on, a message only about the day or a feeling is kept
KEEPS = (
    "a message only about how the user's own day went, what they did today or how they feel, with no request "
    "(\"rough day, work ran late and I'm wiped\", \"I'm tired\", \"had a lovely walk this evening\", \"feeling great "
    "today\"): it goes into today's entry. Beside a report or a request for another task (\"done my stretches and I'm "
    "feeling great\"), the feeling is a part of its own: give both tasks, never a tie"
)
EXAMPLES = ("today was good, finally finished the essay", "what did I write last Tuesday?", "how was my mood this month?")
_DAY = "The day asked about, exactly as the user said it (\"today\", \"yesterday\", \"last Tuesday\"). Never work out a date. Leave out for today."


def today() -> date:
    return rules.diary_day(clock.now())


def _day(said, on: date) -> date:
    if not said:
        return on
    return timeinput.parse_past_date(str(said), on)  # a day gone by: "tuesday" is the last one


async def _streak(user_id: int, on: date) -> int:
    return rules.streak(await database.run(store.db_days, user_id), on)


def changed(user_id: int) -> None:
    summaries.changed(TASK, user_id)


async def _clear_ask(user_id: int, day: date) -> None:
    """Writing or choosing a mood answers the evening ask: it leaves the hub."""
    there = await database.run(store.db_clear_ask, user_id, day, clock.now())
    if there is not None and there[0] and there[1]:
        await cards.delete(there[0], there[1])


# --- writing ------------------------------------------------------------------------------------------------
async def keep(user_id: int, channel_id: int | None, on: date, words: str, said_mood=None) -> str:
    """Words kept for a day, added to its entry (a second Write, or another message, appends); the mood
    if the words gave one; the line said, with Undo and, with no mood yet, a button a level. Never the words."""
    try:
        kept = await database.run(store.db_append, user_id, on, words.strip(), clock.now())
        was_there = kept.notes > 1
        said = mood.checked(said_mood) if mood.on() else None
        if said:
            kept = await database.run(store.db_set_mood, user_id, on, mood.CURRENT.name, said, clock.now(), True)
    except Exception:
        log.exception("Diary: an entry could not be saved")  # never with its words
        raise UserError(NOT_SAVED) from None
    await _clear_ask(user_id, on)
    changed(user_id)
    line = rules.saved_line(kept, await _streak(user_id, on), added=was_there)
    undo_row = (_undo_button(on),)
    if not mood.on() or kept.has_mood:
        message_id = await cards.send(channel_id, Card(line, (undo_row,)))
    else:
        # No mood yet: the line asks, with a button a level
        message_id = await cards.send(channel_id, Card(f"{line}\n-# how was it?", (mood.buttons(TASK, MOOD, on.isoformat()), undo_row)))
    return line if message_id is not None else "not shown"


async def write(request: Request, data: dict, guessed: frozenset):
    """A diary entry: the words as sent, added to the day's entry; the mood if the words gave one; a mention of
    pain (and where) for the gym's pain tracker, when the gym is on: never the words."""
    said = await keep(request.user.id, request.channel_id, today(), request.text, data.get("mood"))
    if data.get("pain") and config.GYM_ENABLED:
        from tasks.gym import pain

        await pain.from_diary(request.user.id, today(), str(data.get("body_part") or ""))
    return Shown(said)


def write_button(day: date, label: str = WRITE_LABEL) -> Button:
    """✍️ Write (blurple): opens the form with one long box."""
    return Button(label, TASK, WRITE, day.isoformat(), emoji="✍️", style=cards.PRIMARY)


def ask_row(day: date) -> tuple:
    """The evening ask's row: ✍️ Write, then a button a mood."""
    return (write_button(day), *(mood.buttons(TASK, MOOD, day.isoformat()) if mood.on() else ()))


def form(day: date) -> cards.Form:
    return cards.Form(FORM_TITLE, TASK, WRITTEN, (cards.Field("words", "Your day", placeholder="A few words, or as many as you like", long=True),), arg=day.isoformat())


async def on_write(press: cards.Press) -> str:
    """✍️ Write, on the ask or after a mood: the form, for that day."""
    day = date.fromisoformat(press.arg) if press.arg else today()
    await press.open_form(form(day))
    return "the diary's form opened"


async def on_written(press: cards.Press) -> str:
    """What was typed in the form: kept for that day, as a message would be. The words never in the log."""
    day = date.fromisoformat(press.arg) if press.arg else today()
    words = str((press.fields or {}).get("words") or "").strip()
    if not words:
        raise UserError("Nothing was written: the diary is as it was.")
    line = await keep(press.user.id, press.channel_id, day, words)
    there = await store.entry(press.user.id, day)
    if there is not None:
        # The ask, or the line after a mood: its button has done its job
        await press.update(Card(rules.saved_line(there, await _streak(press.user.id, today())), ((_undo_button(day),),)))
    return "written in the form" if line != "not shown" else "not shown"


# --- a reply to the evening ask is the day's entry ---------------------------------------------------------------
_asks: dict[int, tuple[int, date]] = {}  # the evening ask's message: (whose, which day), for a reply to it


def remember_ask(message_id: int, user_id: int, day: date) -> None:
    _asks[message_id] = (user_id, day)


async def load_asks() -> None:
    """At start: the asks of the last two diary days, so a reply to one still finds it after a restart."""
    for message_id, user_id, day in await database.run(store.db_recent_asks, today() - timedelta(days=1)):
        remember_ask(message_id, user_id, day)


def claims(message_id: int | None) -> bool:
    return message_id is not None and message_id in _asks


async def take_reply(ctx) -> str:
    """A reply to the evening ask (or to the line it became): the reply's words kept for its day."""
    user_id, day = _asks[ctx.reply_target_id]
    if user_id != ctx.user.id:
        raise UserError("That diary is not yours.")
    return await keep(user_id, ctx.channel_id, day, ctx.text)


def _undo_button(day: date) -> Button:
    return Button("Undo", TASK, UNDO, day.isoformat(), emoji="↩️", style=cards.PRIMARY)


async def _undo_last(db_run, user_id: int, day: date) -> str | None:
    """Undo the last change to a day's entry: the last message written (and the mood said with it),
    else the last mood change. The line to say, or None with nothing to undo."""
    now = clock.now()
    taken = await db_run(store.db_undo_write, user_id, day, now)
    if taken is True:
        return f"{ICON} Undone · nothing kept for {rules.short(day)}"
    if taken is not None:
        return f"{ICON} Undone · {rules.short(day)} as it was"
    back = await db_run(store.db_undo_mood, user_id, day, now)
    if back is None:
        return None
    return f"{ICON} Mood · back to {mood.shown(back.mood_scale, back.mood) or 'none'}"


async def set_mood(request: Request, data: dict, guessed: frozenset):
    """ "actually today was ok": the day's mood, with an undo."""
    if not mood.on():
        raise UserError("The diary keeps no mood: DIARY_MOOD is off.")
    said = mood.checked(data.get("mood"))
    if said is None:
        raise UserError("Which mood? " + ", ".join(level.label for level in mood.CURRENT.levels) + ".")
    day = _day(data.get("day"), today())
    kept = await database.run(store.db_set_mood, request.user.id, day, mood.CURRENT.name, said, clock.now())
    await _clear_ask(request.user.id, day)
    changed(request.user.id)
    message_id = await cards.send(request.channel_id, Card(rules.mood_line(kept), ((_undo_button(day),),)))
    return Shown(rules.mood_line(kept) if message_id is not None else "not shown")


async def undo(request: Request, data: dict, guessed: frozenset) -> str:
    """ "undo that" after an entry or a mood change: the last message written, or the mood as it was."""
    day = _day(data.get("day"), today())
    line = await _undo_last(database.run, request.user.id, day)
    if line is None:
        raise UserError("There is nothing in the diary to undo.")
    changed(request.user.id)
    return line


# --- reading back -------------------------------------------------------------------------------------------
SPANS = ("day", "week", "month")


async def show(request: Request, data: dict, guessed: frozenset) -> str:
    """Read back, in place: a day (its words only when asked for), a week or a month."""
    on = today()
    span = str(data.get("span") or "day").lower()
    if span == "week" or span == "month":
        days = rules.week_of(on) if span == "week" else rules.month_of(on)
        found = await database.run(store.db_between, request.user.id, days[0], days[-1])
        label = "This week" if span == "week" else f"{on:%B}"
        if data.get("moods"):
            return rules.mood_answer(found, days, label)
        return rules.span_answer(found, days, on, label)
    day = _day(data.get("day"), on)
    return rules.day_answer(await store.entry(request.user.id, day), day, on, bool(data.get("words")))


# --- deleting -----------------------------------------------------------------------------------------------
async def delete_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    day = _day(data.get("day"), today())
    there = await store.entry(request.user.id, day)
    if there is None:
        raise UserError(f"There is nothing in the diary for {rules.short(day)}.")
    return Proposal(
        lines=(f"**{rules.short(day)}** · {there.notes} note{'' if there.notes == 1 else 's'}" + (f" · {mood.shown(there.mood_scale, there.mood)}" if mood.on() and there.has_mood else ""), "-# its words go for good"),
        data={"day": day.isoformat()}, kind="remove", destructive=True, confirm_label="Delete",
    )


async def delete_save(request: Request, data: dict) -> str:
    day = date.fromisoformat(data["day"])
    await database.run(store.db_delete, request.user.id, day)
    changed(request.user.id)
    return f"🗑️ {ICON} {rules.short(day)} · deleted"


async def delete_check(request: Request, data: dict) -> str:
    return "still there" if await store.entry(request.user.id, date.fromisoformat(data["day"])) is not None else ""


# --- the buttons ----------------------------------------------------------------------------------------------
async def on_mood(press: cards.Press) -> str:
    """A mood button (under a saved line, or on the evening ask): that day's mood."""
    day_text, _, key = press.arg.partition(":")
    said = mood.checked(key)
    if said is None:
        return "not a mood of this scale"
    day = date.fromisoformat(day_text)
    kept = await press.db.run(store.db_set_mood, press.user.id, day, mood.CURRENT.name, said, clock.now())
    asked = await press.db.run(store.db_ask, press.user.id, day)
    await press.db.run(store.db_clear_ask, press.user.id, day, clock.now())
    changed(press.user.id)
    line = rules.saved_line(kept, await _streak(press.user.id, today()))
    if kept.text:
        await press.update(Card(line, ((_undo_button(day),),)))
    else:
        # A mood with no words yet: one small offer, on this line only, never again
        await press.update(Card(f"{line}\n-# a few words too?", ((write_button(day, ADD_LABEL), _undo_button(day)),)))
    if asked is not None and asked[1] and asked[1] != press.message_id and asked[0]:
        await cards.delete(asked[0], asked[1])  # the evening ask, if this was the line under an entry
    return line


async def on_undo(press: cards.Press) -> str:
    day = date.fromisoformat(press.arg)
    line = await _undo_last(press.db.run, press.user.id, day) or f"{ICON} Nothing to undo"
    changed(press.user.id)
    await press.update(Card(line))
    return line


def register() -> None:
    cards.register(TASK, MOOD, on_mood)
    cards.register(TASK, UNDO, on_undo)
    cards.register(TASK, WRITE, on_write, opens_form=True)
    cards.register(TASK, WRITTEN, on_written, private=True)


# --- the evening ask -------------------------------------------------------------------------------------------
async def ask_job(job: scheduler.Job) -> None:
    """Scheduler handler: if nothing is written today, one gentle ask at the bottom of the hub. Once a day, never again."""
    from core.users import get_user_by_discord_id

    channel_id = hub.channel_id()
    owner = await get_user_by_discord_id(int(config.OWNER_ID)) if config.OWNER_ID else None
    if channel_id is None or owner is None:
        scheduler.note(job, "not asked: no hub, or no owner")
        return
    on = today()
    if await store.entry(owner.id, on) is not None:
        scheduler.note(job, "not asked: today is written")
        return
    if not await database.run(store.db_claim_ask, owner.id, on, clock.now()):
        scheduler.note(job, "not asked: asked already today")
        return
    first = Card(rules.ASK)
    item = Item("the diary", TIMED, when=clock.now(), short=())
    message_id = await notify.post(KIND, channel_id, first, user_id=owner.id, item=item, key=f"diary{on.isoformat()}")
    if message_id is None:
        scheduler.note(job, "not asked: the hub can't be found")
        return
    # Plan my day, when it is on: one small line from 8 pm offering tomorrow (core/planning.py)
    from core import planning

    offer = planning.offer_line(clock.now())
    await cards.edit(channel_id, message_id, Card(rules.ASK + (f"\n{offer}" if offer else ""), (ask_row(on),)))
    await database.run(store.db_asked, owner.id, on, channel_id, message_id)
    remember_ask(message_id, owner.id, on)
    await messages.record(message_id, channel_id, lifetime=messages.DAY, task=TASK, user_id=owner.id)
    scheduler.note(job, "asked")


async def today_job(job: scheduler.Job) -> None:
    """Scheduler handler, 6 pm: the Today card is drawn again, so a day not written yet gets its line."""
    from core.users import get_user_by_discord_id

    owner = await get_user_by_discord_id(int(config.OWNER_ID)) if config.OWNER_ID else None
    if owner is None:
        scheduler.note(job, "nothing drawn: no owner")
        return
    changed(owner.id)
    scheduler.note(job, "the Today card drawn again for the evening")


# --- what extraction is told and offered ----------------------------------------------------------------------
async def state(request: Request) -> State:
    """Whether today is written, and the streak: never a word of what was written."""
    on = today()
    there = await store.entry(request.user.id, on)
    return State("The user's diary (its words are never given here)", (f"today: {'written' if there else 'not written yet'}", f"streak: {await _streak(request.user.id, on)} days"), "nothing yet")


_PAIN = (
    Field("pain", "True when the words speak of pain or discomfort in the body (\"my shoulder's sore\").", BOOLEAN),
    Field("body_part", "With pain: where, in a word or two (\"shoulder\")."),
)


def actions() -> list:
    from core.actions import EACH_DAY, SEE, SET_UP, Action

    found = [
        Action(
            "diary_write",
            "A diary entry: the user's words about their day or how they feel, to keep (\"today was good, finally finished the "
            "essay\", \"add to today's diary: saw Sam\"). The code keeps the words exactly as sent: give only the mood, and only "
            "if the words make it clear. A log: no card.",
            ((mood.field(),) if mood.on() else ()) + _PAIN, needs_card=False, run=write, undo=lambda request, data: undo(request, {}, frozenset()), purpose=EACH_DAY, say=("today was good",),
        ),
        Action(
            "diary_show",
            "The user asks to read their diary back: a day (\"what did I write last Tuesday?\" -> day last Tuesday, words true; "
            "\"how was yesterday in my diary?\" -> day yesterday), the week (\"show this week's diary\" -> span week), or their "
            "mood over a while (\"how was my mood this month?\" -> span month, moods true).",
            (Field("day", _DAY), Field("span", "day, week (this week) or month (this month). Leave out for one day.", choices=SPANS),
             Field("words", "True only when the user asks what they wrote, to read the words.", BOOLEAN),
             Field("moods", "True when the user asks about their mood over the week or month.", BOOLEAN)),
            needs_card=False, run=show, purpose=SEE, say=("show this week's diary",),
        ),
        Action(
            "diary_delete", "Delete a day's diary entry (\"delete today's diary\").", (Field("day", _DAY),),
            prepare=delete_card, apply=delete_save, verify=delete_check, purpose=SET_UP, say=("delete today's diary",),
        ),
    ]
    if mood.on():
        found[1:1] = [
            Action("diary_mood", "The mood of a day changed or said on its own (\"actually today was ok\", \"yesterday was a bad day\").",
                   (mood.field(required=True), Field("day", _DAY)), needs_card=False, run=set_mood, purpose=EACH_DAY, say=("actually today was ok",)),
            Action("diary_undo", "Undo the last change of a day's mood (\"undo that\" straight after it).", (Field("day", _DAY),), needs_card=False, run=undo, purpose=EACH_DAY, say=("undo that",)),
        ]
    return found
