import asyncio
import logging
from datetime import date, timedelta

from core import cards, clock, config, database, design, hubcard, names, scheduler, summaries
from core import day as days
from core.actions import BOOLEAN, EACH_DAY, SEE, SET_UP, Action, Field, Proposal, Request, Shown, State
from core.cards import Button, Card
from core.errors import UserError
from tasks.reading import pick, rules, sources, store
from tasks.reading.rules import ICON, LABELS, TASK, THEMES, TITLE, Candidate, Read

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The daily read's words, its morning job and its buttons.
#
#   5:30 am       the feeds read, the new items' pages read down to their text
#                 (never a paywall, never a headline alone), Claude picks one
#                 for today's theme with a TL;DR from its text
#   6:00 am       its card in the hub, under the other task cards: the title
#                 as a link, the source, the reading time, the TL;DR small,
#                 👍 and 👎; the briefing's overview has one line
#   in words      another one, something shorter, something deeper, save it
#                 for later (a to-do with the link), what have I read this
#                 week, more like this, less news, more about agents, harder,
#                 what do you know about what I like, add or remove a source
#
# A source that fails is quiet (logged); only every source failing three
# days running is something to look at (the task's attention item).
# ---------------------------------------------------------------------------
PICK_JOB, CARD_JOB = "pick", "card"
TEXT_KEPT = 1500  # words of an article kept with the day's candidates
TRIES = 12  # pages read at most to find the day's candidates


def today() -> date:
    return days.today()


def changed(user_id: int) -> None:
    hubcard.changed(TASK, user_id, lambda: hub_card(user_id))
    summaries.changed(TASK, user_id)


# --- the card ---------------------------------------------------------------------------------------------------
def buttons(read: Read) -> tuple:
    day = read.day.isoformat()
    row = [
        Button("", TASK, rules.VOTE, f"{day}:up", emoji="👍", style=cards.PRIMARY),
        Button("", TASK, rules.VOTE, f"{day}:down", emoji="👎", style=cards.PRIMARY),
    ]
    if read.vote < 0:
        row.append(Button("Another one", TASK, rules.ANOTHER_BUTTON, day, emoji="🔄", style=cards.PRIMARY))
    return (tuple(row),)


def card(read: Read) -> Card:
    lines = [rules.headline(read), *(design.small(line) for line in read.tldr.splitlines())]
    if read.vote:
        lines.append(design.small(rules.vote_note(read)))
    layout = (design.topic(design.card_title(f"{ICON} {TITLE} · {LABELS.get(read.theme, read.theme)}"), [design.Entry("\n".join(lines), design.QUIET, buttons(read)[0])], status=design.QUIET),)
    return Card(rules.card_text(read), buttons(read), layout)


async def hub_card(user_id: int) -> Card | None:
    read = await store.current(user_id, today())
    return card(read) if read is not None else None


async def post_job(job) -> None:
    """The morning routine's step: the day's read, under the other task cards."""
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if user_id is None:
        scheduler.note(job, "not posted: there is nobody to post for")
        return
    posted = await hubcard.post(TASK, user_id, lambda: hub_card(user_id))
    scheduler.note(job, "posted" if posted is not None else "not posted: no read picked today")


# --- reading the sources and picking --------------------------------------------------------------------------------
async def sources_for(user_id: int) -> list[sources.Source]:
    """The starter list, with what was added or removed in words."""
    found = {each.url: each for each in sources.starter()}
    for url, name, theme, state in await database.run(store.db_source_changes, user_id):
        if state == store.REMOVED:
            found.pop(url, None)
        else:
            found[url] = sources.Source(name, url, theme)
    return list(found.values())


async def _items(user_id: int, day: date) -> list[rules.Item]:
    """Every feed's items; a feed that fails is logged and left out. Records the day's fetch."""
    listed = await sources_for(user_id)
    read = await asyncio.gather(*(sources.feed(each) for each in listed), return_exceptions=True)
    found, failed = [], 0
    for source, result in zip(listed, read):
        if isinstance(result, BaseException):
            failed += 1
            log.info("Daily read: %s could not be read (%s)", source.name, type(result).__name__)
        else:
            found += result
    await database.run(store.db_fetched, user_id, day, len(listed), failed)
    return found


async def candidates(user_id: int, day: date, theme: str) -> list[Candidate]:
    """Up to CANDIDATES new articles whose text could be read, today's theme first. Kept for the day."""
    now = clock.now()
    seen = await database.run(store.db_seen, user_id)
    ordered = rules.for_theme(rules.eligible(await _items(user_id, day), seen, now), theme)
    found: list[Candidate] = []
    for item in ordered[:TRIES]:
        try:
            text = await sources.article(item.url)
        except Exception as problem:
            log.info("Daily read: an article could not be read (%s)", type(problem).__name__)
            continue
        if not rules.readable(text):
            continue  # a paywall, a teaser or a link post: never a TL;DR from the headline alone
        found.append(Candidate(item, " ".join(text.split()[:TEXT_KEPT]), rules.minutes(text)))
        if len(found) >= rules.CANDIDATES:
            break
    await database.run(store.db_keep_candidates, user_id, day, found)
    return found


async def _theme(user_id: int, day: date, profile: rules.Profile) -> str:
    monday = day - timedelta(days=day.weekday())
    shown = await database.run(store.db_themes_between, user_id, monday, day - timedelta(days=1))
    return rules.theme_for(day, profile, shown)


async def _show(user_id: int, day: date, chosen: Candidate, tldr: str, rating: tuple[int, int] | None = None) -> Read:
    read = Read(chosen.item.url, chosen.item.title, chosen.item.source, chosen.item.theme, chosen.minutes, tldr, day,
                difficulty=rating[0] if rating else None, practicality=rating[1] if rating else None)
    await database.run(store.db_show, user_id, read, clock.now())
    changed(user_id)
    return read


async def pick_today(user_id: int, day: date) -> Read | None:
    """The day's read: the sources read, Claude's pick shown. None when nothing could be picked."""
    profile = await database.run(store.db_profile, user_id)
    theme = await _theme(user_id, day, profile)
    found = await candidates(user_id, day, theme)
    picked = await pick.choose(found, theme, profile)
    if picked is None:
        return None
    return await _show(user_id, day, *picked)


async def pick_job(job) -> None:
    """Before the briefing: the day's read, once. Safe to run twice."""
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if user_id is None:
        scheduler.note(job, "not picked: there is nobody to pick for")
        return
    day = today()
    if await store.current(user_id, day) is not None:
        scheduler.note(job, "not picked: today's is picked already")
        return
    read = await pick_today(user_id, day)
    scheduler.note(job, f"picked: {LABELS.get(read.theme, read.theme)}, {read.minutes} min" if read else "not picked: no article could be read today")


async def another(user_id: int, kind: str = rules.ANOTHER) -> Read:
    """Another one (shorter, deeper) from the day's articles, read afresh if they have run out."""
    day = today()
    shown = await store.current(user_id, day)
    seen = await database.run(store.db_seen, user_id)
    profile = await database.run(store.db_profile, user_id)
    theme = shown.theme if shown is not None else await _theme(user_id, day, profile)
    found = [each for each in await database.run(store.db_candidates, user_id, day) if each.item.url not in seen]
    if not found:
        found = await candidates(user_id, day, theme)
    fitting = [each for each in found if rules.fits(each, kind, shown.minutes if shown else None)]
    if not fitting:
        raise UserError(f"{ICON} Nothing {'shorter' if kind == rules.SHORTER else 'deeper' if kind == rules.DEEPER else 'else'} to read today.")
    picked = await pick.choose(fitting, theme, profile, kind)
    if picked is None:
        raise UserError(f"{ICON} Another one couldn't be picked just now. Try again in a moment.")
    return await _show(user_id, day, *picked)


# --- the buttons ----------------------------------------------------------------------------------------------------
async def _vote(user_id: int, day: date, up: bool) -> Read | None:
    shown = await store.current(user_id, day)
    if shown is None:
        return None
    profile = await database.run(store.db_profile, user_id)
    await database.run(store.db_set_profile, user_id, rules.voted(profile, shown.theme, up), clock.now())
    return await database.run(store.db_vote, user_id, shown.url, 1 if up else -1)


async def on_vote(press: cards.Press) -> str:
    day_text, _, which = press.arg.partition(":")
    read = await _vote(press.user.id, date.fromisoformat(day_text), which == "up")
    if read is None:
        return "that read is gone"
    await press.update(card(read))
    changed(press.user.id)
    return rules.vote_note(read)


async def on_another(press: cards.Press) -> str:
    try:
        read = await another(press.user.id)
    except UserError as said:
        return str(said)
    await press.update(card(read))
    return f"another: {read.minutes} min"


def register() -> None:
    cards.register(TASK, rules.VOTE, on_vote)
    cards.register(TASK, rules.ANOTHER_BUTTON, on_another)


# --- plain words ----------------------------------------------------------------------------------------------------
async def answer_another(request: Request, data: dict, guessed: frozenset):
    kind = data.get("kind") if data.get("kind") in rules.KINDS else rules.ANOTHER
    read = await another(request.user.id, kind)
    message_id = await cards.send(request.channel_id, card(read))
    return Shown(rules.headline(read) if message_id is not None else "not shown")


async def show(request: Request, data: dict, guessed: frozenset) -> str:
    if data.get("what") == "profile":
        return rules.profile_text(await database.run(store.db_profile, request.user.id))
    day = today()
    reads = await database.run(store.db_between, request.user.id, day - timedelta(days=day.weekday()), day)
    return rules.week_answer(reads)


async def save_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    if not config.TODOS_ENABLED:
        raise UserError(f"{ICON} To-dos are off, so there is nowhere to save it for later.")
    read = await store.current(request.user.id, today())
    if read is None:
        raise UserError(f"{ICON} There is no read today to save.")
    return Proposal(lines=(f"📝 **Read: {read.title}** · any day", design.small(read.url)), data={"url": read.url, "title": read.title})


async def save_apply(request: Request, data: dict) -> str:
    # The to-dos task's own store and its own word that it changed: the one write into another task's
    # list, by Alex's word ("save it for later adds a to-do with the link")
    from tasks.todos import plain as todos_plain
    from tasks.todos import store as todos_store

    now = clock.now()
    await database.run(todos_store.db_add, request.user.id, f"Read: {data['title']} {data['url']}", None, today(), now)
    await database.run(store.db_saved, request.user.id, data["url"])
    todos_plain.changed(request.user.id)
    return f"📝 Saved for later · on your to-dos"


async def save_check(request: Request, data: dict) -> str:
    from tasks.todos import store as todos_store

    found = [each for each in await todos_store.every(request.user.id) if data["url"] in each.text]
    return "" if found else "the to-do isn't there"


async def tune_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    before = await database.run(store.db_profile, request.user.id)
    after = before
    if data.get("like_this") is not None:
        read = await store.current(request.user.id, today())
        if read is not None:
            after = rules.voted(after, read.theme, bool(data["like_this"]))
    after = rules.tuned(after, str(data.get("more_theme") or ""), str(data.get("less_theme") or ""), str(data.get("more_topic") or ""), str(data.get("less_topic") or ""), str(data.get("level") or ""))
    lines = rules.changes(before, after)
    if not lines:
        raise UserError(f"{ICON} That is how the daily read is already.")
    return Proposal(lines=tuple(lines), data={"profile": after.as_dict()}, kind="change")


async def tune_apply(request: Request, data: dict) -> str:
    await database.run(store.db_set_profile, request.user.id, rules.Profile.from_dict(data["profile"]), clock.now())
    return f"{ICON} Noted for the next reads"


async def tune_check(request: Request, data: dict) -> str:
    kept = await database.run(store.db_profile, request.user.id)
    return "" if kept.as_dict() == rules.Profile.from_dict(data["profile"]).as_dict() else "the change didn't save"


async def source_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    listed = await sources_for(request.user.id)
    if data.get("remove"):
        try:
            gone = names.find(listed, str(data.get("name") or data.get("url") or ""), lambda each: each.name)
        except names.Unnamed:
            raise UserError("Which source?")
        except (names.Unknown, names.Ambiguous):
            raise UserError("Sources: " + ", ".join(each.name for each in listed) + ".")
        return Proposal(lines=(f"**{gone.name}** · {LABELS[gone.theme]}",), data={"url": gone.url, "name": gone.name, "theme": gone.theme, "state": store.REMOVED}, kind="remove")
    url, theme = str(data.get("url") or "").strip(), str(data.get("theme") or "")
    if not url.startswith("http"):
        raise UserError("Which feed? Its address, starting with https://")
    if theme not in THEMES:
        raise UserError("Which theme is it for: " + ", ".join(LABELS[each] for each in THEMES) + "?")
    try:
        found = await sources.feed(sources.Source(str(data.get("name") or url), url, theme))
    except Exception:
        raise UserError("That feed couldn't be read: nothing added.") from None
    if not found:
        raise UserError("That feed has nothing in it: nothing added.")
    name = str(data.get("name") or "").strip() or found[0].source
    return Proposal(lines=(f"**{name}** · {LABELS[theme]} · {len(found)} items now", design.small(url)), data={"url": url, "name": name, "theme": theme, "state": store.ADDED})


async def source_apply(request: Request, data: dict) -> str:
    await database.run(store.db_set_source, request.user.id, data["url"], data["name"], data["theme"], data["state"], clock.now())
    return f"{ICON} {data['name']} · {'added' if data['state'] == store.ADDED else 'removed'}"


async def source_check(request: Request, data: dict) -> str:
    listed = {each.url for each in await sources_for(request.user.id)}
    there = data["url"] in listed
    return "" if there == (data["state"] == store.ADDED) else "the change didn't save"


async def state(request: Request) -> State:
    read = await store.current(request.user.id, today())
    lines = [f"today's read: {read.title} ({LABELS[read.theme]}, {read.minutes} min)" if read else "today's read: none yet"]
    lines.append("sources: " + ", ".join(each.name for each in await sources_for(request.user.id)))
    return State("The user's daily read", tuple(lines), "nothing yet")


def actions() -> list:
    themes = tuple(THEMES)
    return [
        Action(
            "reading_another",
            "Another article instead of today's (\"another one\", \"something else to read\"), or one shorter or deeper "
            "(\"something shorter\" -> kind shorter, \"something deeper\" -> kind deeper).",
            (Field("kind", "another, shorter or deeper. Leave out for just another.", choices=rules.KINDS),),
            needs_card=False, run=answer_another, purpose=EACH_DAY, say=("another one", "something shorter"),
        ),
        Action(
            "reading_save",
            "Save today's read for later (\"save it for later\", \"save this article\"): a to-do with its link.",
            (), prepare=save_card, apply=save_apply, verify=save_check, purpose=EACH_DAY, say=("save it for later",),
        ),
        Action(
            "reading_show",
            "What the user has read this week (\"what have I read this week?\" -> what week), or what the daily read knows "
            "about what they like (\"what do you know about what I like to read?\" -> what profile).",
            (Field("what", "week or profile.", choices=("week", "profile"), required=True),),
            needs_card=False, run=show, purpose=SEE, say=("what have I read this week?",),
        ),
        Action(
            "reading_tune",
            "Shape what the daily read picks: \"more like this\" -> like_this true, \"less like this\" -> like_this false, "
            "\"less news\" -> less_theme news, \"more programming\" -> more_theme programming, \"more about agents\" -> "
            "more_topic agents, \"harder\", \"easier\" or \"more practical\" -> level.",
            (
                Field("like_this", "true for more like today's read, false for less like it.", BOOLEAN),
                Field("more_theme", "A theme to have more often.", choices=themes),
                Field("less_theme", "A theme to have less often.", choices=themes),
                Field("more_topic", "A topic to have more about, in a word or two (\"agents\")."),
                Field("less_topic", "A topic to have less about, in a word or two."),
                Field("level", "harder, easier, or more_practical (\"more practical\", \"more hands-on\").", choices=(rules.HARDER, rules.EASIER, rules.PRACTICAL)),
            ),
            prepare=tune_card, apply=tune_apply, verify=tune_check, purpose=SET_UP, say=("more like this", "less news"),
        ),
        Action(
            "reading_source",
            "Add a feed to the daily read's sources (\"add https://example.com/feed.xml to my reading, for programming\"), or "
            "remove one (\"stop using The Verge\" -> remove true, name The Verge).",
            (
                Field("remove", "true to remove a source.", BOOLEAN),
                Field("url", "The feed's address, as given."),
                Field("name", "The source's name, as said."),
                Field("theme", "Which theme it is for, when adding.", choices=themes),
            ),
            prepare=source_card, apply=source_apply, verify=source_check, purpose=SET_UP, say=("remove The Verge from my reading",),
        ),
    ]


ONLY_FOR = (
    "The user's daily read: one article a day for keeping learning (AI usage, programming, tech news). Asking for another "
    "one, something shorter or deeper, saving it for later, what they have read this week, shaping what it picks (\"more "
    "like this\", \"less news\", \"more about agents\", \"harder\"), what it knows about what they like, and adding or "
    "removing a source. Not a to-do in general (the to-dos task), and not a question about a tech topic itself (chat)."
)
EXAMPLES = ("another one", "save it for later", "less news")
