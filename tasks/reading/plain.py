import asyncio
import logging
from datetime import date, timedelta

from core import cards, channels, clock, config, database, design, names, scheduler, summaries, surface, thumbsup, timeinput
from core import day as days
from core.actions import BOOLEAN, EACH_DAY, INTEGER, PREPARED, SEE, SET_UP, Action, DayItem, Field, Proposal, Request, Shown, State
from core.cards import Button
from core.errors import UserError
from tasks.reading import news, pick, rules, sources, store
from tasks.reading.news import ALL_TOPICS, FROM_THEME, ICON, LABELS, TITLE, Story
from tasks.reading.rules import TASK

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The morning news (behind READING_ENABLED, off): its morning jobs, its cards
# and its words.
#
#   5:30 am       every feed read at once (a timeout each; one that fails is
#                 noted in the run log and skipped), the window's free items
#                 each story once (tasks/reading/news.py), Claude picks 7 or 8
#                 and writes their TL;DRs (tasks/reading/pick.py), the set kept
#   6:00 am       a step of the morning routine, before the briefing: the
#                 cards of earlier days deleted from #news, then a card a
#                 story (Alex, 21 Oct: "could each news article be its own
#                 card?"), in the topics' order; round 7's hub has one line
#                 that links to the first (`day_items`)
#   👍 on a card  he liked or read it: a signal for later picks, silent
#                 (core/thumbsup.py, a kind of its own); taken away, it goes
#   in words      in #news, #inbox or a direct message: another one (a new
#                 card in #news), more like the housing one, less AI, skip
#                 housing tomorrow; as a reply to a card, more like this or
#                 less of this; what do you know about what I like, the news,
#                 add or remove a source
#
# #news is NEWS_CHANNEL_ID if set, else the one the bot made beside the hub
# (kept in reading_news_channel), else made now. The dev bot never makes one
# (docs/RULES.md): without NEWS_CHANNEL_ID in .env.dev it posts no cards.
#
# What an article says goes to Claude and into the set's own message only:
# never a log, #bot-log, a notification or the status line.
# ---------------------------------------------------------------------------
PICK_JOB = "pick"
POST_JOB = "post"  # the cards in #news, a step of the morning routine
NEWS = "news"  # the channel, by its role in config.CHANNELS and its name
LIKED, UNLIKED = "liked", "unliked"  # 👍 on a card, and taken away (core/thumbsup.py)
FEED_TIMEOUT = 20  # seconds a feed gets
PAGE_TIMEOUT = 15  # seconds a chosen article's page gets
USABLE_WORDS = 80  # less readable text than this on a page that loaded is as a page that failed: its snippet stands in
TRIES = 3  # pages read at most for one slot, a paywalled one replaced by the next of its topic
SHOWN_FOR = 7  # days a story shown is never shown again


def today() -> date:
    return days.today()


def changed(user_id: int) -> None:
    summaries.changed(TASK, user_id)  # the briefing's second message is drawn again


# --- the sources ---------------------------------------------------------------------------------------------------
async def sources_for(user_id: int) -> list[sources.Source]:
    """The starter feeds, with what was added or removed in words (an old daily read's theme read as its topic)."""
    found = {each.url: sources.Source(each.name, each.url, FROM_THEME.get(each.theme, each.theme), each.region) for each in sources.starter()}
    for url, name, theme, state in await database.run(store.db_source_changes, user_id):
        if state == store.REMOVED:
            found.pop(url, None)
        else:
            found[url] = sources.Source(name, url, FROM_THEME.get(theme, theme))
    return [each for each in found.values() if each.theme in ALL_TOPICS]


async def read_feeds(user_id: int, day: date) -> tuple[list, list[str]]:
    """Every feed's items, read at once with a timeout each; the names of those that failed. Records the day's fetch."""
    listed = await sources_for(user_id)
    read = await asyncio.gather(*(asyncio.wait_for(sources.feed(each), FEED_TIMEOUT) for each in listed), return_exceptions=True)
    found, failed = [], []
    for source, result in zip(listed, read):
        if isinstance(result, BaseException):
            failed.append(source.name)
            log.info("Morning news: %s could not be read (%s)", source.name, type(result).__name__)
        else:
            found += result
    await database.run(store.db_fetched, user_id, day, len(listed), len(failed))
    return found, failed


async def text_of(item) -> str | None:
    """A chosen article's text, for its TL;DR. None when the page is behind a paywall (it says it is not free, or it
    reads as one): that story is dropped, never summarised from its snippet. The feed snippet stands in only for a page
    that fails to load, times out, or has no readable text on it."""
    try:
        text, paid = await asyncio.wait_for(sources.article_page(item.url), PAGE_TIMEOUT)
    except Exception as problem:
        log.info("Morning news: an article's page could not be read (%s)", type(problem).__name__)
        return item.snippet or item.title
    if paid or rules.paywalled(text):
        log.info("Morning news: a chosen article is behind a paywall: dropped")
        return None
    return text if len(text.split()) >= USABLE_WORDS else (item.snippet or item.title)


async def settled(found: list, chosen: list[int], nexts: list[int], us: set[int], us_most: int) -> list[tuple[int, str]]:
    """Each chosen story with its text, a paywalled one replaced by the next of its topic (the ranked next first, then
    the topic's others in order), TRIES pages at most a slot, never past the day's US-only allowance. A slot with
    nothing free to read is left out."""
    texts = await asyncio.gather(*(text_of(found[index]) for index in chosen))
    used = set(chosen)
    kept = [(index, text) for index, text in zip(chosen, texts) if text is not None]
    for index, text in zip(chosen, texts):
        if text is not None:
            continue
        topic = found[index].theme
        others = [alt for alt in dict.fromkeys([*nexts, *range(len(found))]) if alt not in used and found[alt].theme == topic]
        for alt in others[: TRIES - 1]:
            used.add(alt)
            if alt in us and sum(1 for each, _ in kept if each in us) >= us_most:
                continue
            got = await text_of(found[alt])
            if got is not None:
                kept.append((alt, got))
                break
    order = {index: position for position, index in enumerate(chosen)}
    return sorted(kept, key=lambda pair: order.get(pair[0], len(order) + news.TOPICS.index(found[pair[0]].theme) if found[pair[0]].theme in news.TOPICS else 99))


# --- the morning's set --------------------------------------------------------------------------------------------
async def build(user_id: int, day: date) -> tuple[list[Story], list[str]]:
    """The day's set: read, picked, written and kept; and the feeds that failed. An empty set when nothing could be picked."""
    items, failed = await read_feeds(user_id, day)
    shown = await database.run(store.db_news_shown, user_id, day - timedelta(days=SHOWN_FOR))
    found = news.eligible(items, news.window_start(clock.now()), shown)
    prefs = await database.run(store.db_prefs, user_id)
    liked = await database.run(store.db_liked_stories, user_id)
    skipped = news.skipped_on(prefs, day)
    picked = await pick.choose(found, day, news.guidance(prefs, day, liked), skipped, prefs.us_most)
    if picked is None:
        return [], failed
    chosen, nexts, us = picked
    kept = await settled(found, chosen, nexts, us, prefs.us_most)
    if not kept:
        return [], failed
    tldrs = await pick.write([(found[index], text) for index, text in kept])
    stories = [Story(found[index].url, found[index].title, found[index].source, found[index].theme, tldr, found[index].outlets) for (index, _), tldr in zip(kept, tldrs)]
    await database.run(store.db_put_news, user_id, day, stories, clock.now())
    used = {index for index, _ in kept}
    await database.run(store.db_put_spares, user_id, day, [found[index] for index in nexts if index not in used])
    changed(user_id)
    return stories, failed


async def pick_job(job) -> None:
    """Before the briefing: the day's set, once. Safe to run twice."""
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if user_id is None:
        scheduler.note(job, "not picked: there is nobody to pick for")
        return
    day = today()
    if await database.run(store.db_news, user_id, day) is not None:
        scheduler.note(job, "not picked: today's is picked already")
        return
    stories, failed = await build(user_id, day)
    missing = f"; {len(failed)} feed{'' if len(failed) == 1 else 's'} not read: {', '.join(failed[:6])}{'…' if len(failed) > 6 else ''}" if failed else ""
    scheduler.note(job, (f"{len(stories)} stories" if stories else "not picked: nothing could be picked today") + missing)


# --- #news -----------------------------------------------------------------------------------------------------------
_cannot_make: list[str] = []  # why #news could not be made, for Needs a look (in memory: the next try says again)


def may_make() -> bool:
    """Only live makes #news: the dev bot never makes a channel (docs/RULES.md)."""
    return not config.DEV_DATABASE


async def news_channel(user_id: int) -> int | None:
    """#news: NEWS_CHANNEL_ID, else the one made before, else made now beside the hub. None if there is none."""
    said = config.CHANNELS.get(NEWS)
    if said and surface.place(int(said)) is not None:
        return int(said)
    kept = await database.run(store.db_news_channel, user_id)
    if kept is not None and surface.place(kept) is not None:
        channels.keep(NEWS, kept)
        return kept
    hub = config.CHANNELS.get("hub")
    if not may_make() or not hub or surface.place(int(hub)) is None:
        return None
    try:
        made = await surface.make_place(int(hub), NEWS, "The morning news: a card a story")
    except surface.Failed as problem:
        log.warning("Morning news: #news could not be made (%s)", problem.status or problem)
        _cannot_make[:] = [f"#{NEWS} can't be made: the bot may not make channels (make #{NEWS} beside the hub, or give it Manage Channels)"]
        return None
    _cannot_make.clear()
    await database.run(store.db_set_news_channel, user_id, made, clock.now())
    channels.keep(NEWS, made)
    return made


async def recall_channel(user_id: int) -> int | None:
    """At a start: the #news made before, known by its role again (it listens); nothing is made here."""
    kept = await database.run(store.db_news_channel, user_id)
    if kept is not None and not config.CHANNELS.get(NEWS) and surface.place(kept) is not None:
        channels.keep(NEWS, kept)
    return config.CHANNELS.get(NEWS)


def _noted(message_id: int, channel_id: int) -> None:
    """A card's 👍 is a signal (core/thumbsup.py): liked or read, and taken away."""
    arg = str(message_id)
    thumbsup.signal(message_id, channel_id, Button("Liked", TASK, LIKED, arg, emoji="👍"), Button("Not liked", TASK, UNLIKED, arg))


async def note_cards() -> int:
    """At a start: every card still up has its 👍 again (the registry is in memory)."""
    found = await database.run(store.db_cards_up)
    for channel_id, message_id, _ in found:
        _noted(message_id, channel_id)
    return len(found)


async def clear_before(user_id: int, day: date) -> int:
    """The cards of earlier days deleted from where they went up: only the bot's own news cards. One that can't be
    deleted now stays noted, for the next morning."""
    gone = 0
    for when, url, channel_id, message_id in await database.run(store.db_cards_before, user_id, day):
        try:
            await cards.delete(channel_id, message_id)
        except surface.Gone:
            pass
        except surface.Failed as problem:
            log.info("Morning news: an old card could not be deleted (%s)", problem.status or problem)
            continue
        thumbsup.forget_signal(message_id)
        await database.run(store.db_card_gone, user_id, when, url)
        gone += 1
    return gone


async def post_card(user_id: int, day: date, story: Story, channel_id: int) -> int | None:
    """One story's card, noted before it goes (never posted twice) and up after. None if it could not go."""
    await database.run(store.db_card_sending, user_id, day, story, channel_id)
    try:
        message_id = await cards.send(channel_id, news.story_card(story), silent=True)
    except surface.Failed:
        message_id = None
    if message_id is None:
        await database.run(store.db_card_unsent, user_id, day, story.url)
        return None
    await database.run(store.db_card_up, user_id, day, story.url, message_id)
    _noted(message_id, channel_id)
    return message_id


async def post_day(user_id: int, day: date, stories: list[Story]) -> tuple[int, int, int] | None:
    """The day's cards in #news, in the topics' order, after the earlier days' are deleted: (posted now, there
    already, cleared). A card noted already (up, or cut off mid-post by a start) is never posted again. Raises
    surface.Failed when one could not go, so the job runs once more a minute later; what went up stays up.
    None when there is no #news."""
    channel_id = await news_channel(user_id)
    if channel_id is None:
        return None
    cleared = await clear_before(user_id, day)
    there = await database.run(store.db_cards, user_id, day)
    posted = 0
    for story in news.in_order(stories):
        if story.url in there:
            continue
        if await post_card(user_id, day, story, channel_id) is None:
            changed(user_id)
            raise surface.Failed(f"a card could not be posted in #{NEWS}")
        posted += 1
    changed(user_id)
    return posted, len(there), cleared


async def post_job(job) -> None:
    """The morning routine's step at 6 am: the day's cards in #news (picked now if 5:30's pick has not). Safe to
    run twice."""
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if user_id is None:
        scheduler.note(job, "not posted: there is nobody to post for")
        return
    day = today()
    found = await database.run(store.db_news, user_id, day)
    if found is None:
        await build(user_id, day)
        found = await database.run(store.db_news, user_id, day)
    if found is None or not found[0]:
        scheduler.note(job, "not posted: no morning news today")
        return
    done = await post_day(user_id, day, found[0])
    if done is None:
        scheduler.note(job, f"not posted: there is no #{NEWS}" + ("" if may_make() else " (the dev bot makes none: NEWS_CHANNEL_ID)"))
        return
    posted, there, cleared = done
    scheduler.note(job, (f"{posted} cards posted" if posted else "posted already") + (f", {there} there already" if posted and there else "") + (f"; {cleared} of earlier days deleted" if cleared else ""))


# --- how it is shown in the hub -------------------------------------------------------------------------------------
async def day_items(user_id: int, day: date) -> list:
    """For round 7's hub: one line in the briefing's second message, "📰 8 stories in #news", that links to the first
    card. Before round 7 the news is not in the hub (Alex, 21 Oct): it is asked for in words."""
    if design.current() != design.EMBEDS_ROUND:
        return []
    up = await database.run(store.db_cards_up, user_id, day)
    if not up:
        return []
    channel_id, message_id, _ = up[0]
    return [DayItem(PREPARED, news.pointer(len(up), NEWS), icon=ICON, title=TITLE, link=surface.link(channel_id, message_id))]


async def today_stories(user_id: int) -> list[Story]:
    """Today's stories as he sees them: the cards up (another one too), else the day's set."""
    up = await database.run(store.db_cards_up, user_id, today())
    if up:
        return [story for _, _, story in up]
    found = await database.run(store.db_news, user_id, today())
    return list(found[0]) if found else []


# --- 👍 on a card -----------------------------------------------------------------------------------------------------
async def on_liked(press: cards.Press) -> str:
    """👍 on a story's card (core/thumbsup.py, a signal): he liked or read it, kept for the next picks. Silent."""
    if not await database.run(store.db_like_card, press.user.id, int(press.arg), True, clock.now()):
        return "that card is no story of his"
    return f"{ICON} noted: liked or read"


async def on_unliked(press: cards.Press) -> str:
    await database.run(store.db_like_card, press.user.id, int(press.arg), False, clock.now())
    return f"{ICON} not noted after all"


def register() -> None:
    cards.register(TASK, LIKED, on_liked)
    cards.register(TASK, UNLIKED, on_unliked)


# --- plain words --------------------------------------------------------------------------------------------------------
async def show(request: Request, data: dict, guessed: frozenset):
    """Today's news anywhere (where its cards are, or the cards here when #news has none), or what it knows about
    what he likes."""
    if data.get("what") == "prefs":
        return news.profile_text(await database.run(store.db_prefs, request.user.id), today())
    up = await database.run(store.db_cards_up, request.user.id, today())
    if up:
        channel_id, message_id, _ = up[0]
        place = surface.place(channel_id)
        return f"{news.pointer(len(up), NEWS)}: {surface.link(channel_id, message_id) or (place.mention if place else '')}".rstrip(": ")
    found = await database.run(store.db_news, request.user.id, today())
    if found is None or not found[0]:
        return f"{ICON} No morning news picked today yet."
    message_id = await cards.send(request.channel_id, news.all_in_one(found[0], today()))
    return Shown(news.plain_text(found[0], today()) if message_id is not None else "not shown")


async def another(request: Request, data: dict, guessed: frozenset):
    """ "another one": the best story not shown yet today, its TL;DR written now, as a new card in #news (here, as
    a card, when there is no #news)."""
    day = today()
    found = await database.run(store.db_news, request.user.id, day)
    if found is None:
        raise UserError(f"{ICON} No morning news picked today yet.")
    for _ in range(TRIES):
        item = await database.run(store.db_next_spare, request.user.id, day)
        if item is None:
            raise UserError(f"{ICON} That's every story worth showing today.")
        text = await text_of(item)
        if text is not None:
            break  # one behind a paywall is passed over, never summarised
    else:
        raise UserError(f"{ICON} The next stories are all behind paywalls today.")
    (tldr,) = await pick.write([(item, text)])
    story = Story(item.url, item.title, item.source, item.theme, tldr)
    channel_id = await news_channel(request.user.id) or request.channel_id
    message_id = await post_card(request.user.id, day, story, channel_id)
    if message_id is None:
        await database.run(store.db_unshow_spare, request.user.id, day, item.url)
        raise UserError(f"{ICON} The story couldn't be posted: try again in a minute.")
    changed(request.user.id)
    if channel_id == request.channel_id:
        return Shown(f"another one: {story.title}")
    return Shown(f"another one: {story.title}", also=f"{ICON} One more in #{NEWS}: {surface.link(channel_id, message_id)}")


async def _replied_story(request: Request, data: dict):
    """The story "more like this" or "less of this" means: the card replied to. None when nothing points at one."""
    if not data.get("this"):
        return None
    found = await database.run(store.db_card_of, request.replied_to)
    if found is None or found[0] != request.user.id:
        raise UserError(f"{ICON} Which story? Reply to its card in #{NEWS} with “more like this”, or say it by its topic.")
    return found[2]


async def _liked_story(user_id: int, data: dict):
    """The story "more like the housing one" or "more like the one about the water reform" means: by its topic, or by
    words of its headline (core/names.py); a number is asked about, gently, by topic (the stories have none)."""
    if data.get("like_number") is None and not data.get("like_topic") and not data.get("like_words"):
        return None
    stories = await today_stories(user_id)
    if not stories:
        raise UserError(f"{ICON} No morning news picked today yet.")
    topics = ", ".join(dict.fromkeys(news.CARD_NAMES[each.topic] for each in news.in_order(stories)))
    if data.get("like_topic"):
        of_topic = [each for each in news.in_order(stories) if each.topic == data["like_topic"]]
        if not of_topic:
            raise UserError(f"{ICON} There's no {news.CARD_NAMES.get(data['like_topic'], 'such')} story today. Today's are {topics}.")
        return of_topic[0]
    if data.get("like_words"):
        try:
            return names.find(stories, str(data["like_words"]), lambda each: each.title)
        except names.Ambiguous as which:
            raise UserError(f"{ICON} Which one: " + " or ".join(f"**{each.title}**" for each in which.candidates[:3]) + "?")
        except (names.Unknown, names.Unnamed):
            raise UserError(f"{ICON} Which story? Say it by its topic ({topics}) or a few words of its headline.")
    raise UserError(f"{ICON} Which story? The news has no numbers: say it by its topic, like “more like the housing one”, or reply to its card. Today's are {topics}.")


def _skip_day(said, now) -> date:
    """The day a skip is for: the one said, else the next morning's set (today's, before 5:30 am)."""
    local = days.day_of(now)
    if said:
        return timeinput.parse_date(str(said), local)
    return local if days.local_time(now) < news.RUN_AT else local + timedelta(days=1)


async def steer_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "more like the housing one", "less AI", "skip housing tomorrow", and as a reply to a card "more like this" or
    "less of this": a card that says what changes."""
    before = await database.run(store.db_prefs, request.user.id)
    pointed = await _replied_story(request, data)
    like = pointed if pointed is not None and data.get("this") == "like" else await _liked_story(request.user.id, data)
    if pointed is not None and data.get("this") == "less":
        data = {**data, "less": pointed.topic}
    skip = str(data.get("skip") or "")
    skip_on = _skip_day(data.get("skip_day"), clock.now()) if skip else None
    us = str(data.get("us") or "")
    after = news.steered(before, str(data.get("more") or ""), str(data.get("less") or ""), like, skip, skip_on, today(), us if us in ("more", "less") else "")
    lines = news.changes(before, after)
    if not lines:
        raise UserError(f"{ICON} That is how the morning news is already.")
    return Proposal(lines=tuple(lines), data={"prefs": after.as_dict()}, kind="change")


async def steer_apply(request: Request, data: dict) -> str:
    await database.run(store.db_set_prefs, request.user.id, news.Prefs.from_dict(data["prefs"]), clock.now())
    return f"{ICON} Noted for the next mornings"


async def steer_check(request: Request, data: dict) -> str:
    kept = await database.run(store.db_prefs, request.user.id)
    return "" if kept.as_dict() == news.Prefs.from_dict(data["prefs"]).as_dict() else "the change didn't save"


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
    url, topic = str(data.get("url") or "").strip(), str(data.get("topic") or "")
    if not url.startswith("http"):
        raise UserError("Which feed? Its address, starting with https://")
    if topic not in ALL_TOPICS:
        raise UserError("Which topic is it for: " + ", ".join(LABELS[each] for each in ALL_TOPICS) + "?")
    try:
        found = await sources.feed(sources.Source(str(data.get("name") or url), url, topic))
    except Exception:
        raise UserError("That feed couldn't be read: nothing added.") from None
    if not found:
        raise UserError("That feed has nothing in it: nothing added.")
    name = str(data.get("name") or "").strip() or found[0].source
    return Proposal(lines=(f"**{name}** · {LABELS[topic]} · {len(found)} items now", design.small(url)), data={"url": url, "name": name, "theme": topic, "state": store.ADDED})


async def source_apply(request: Request, data: dict) -> str:
    await database.run(store.db_set_source, request.user.id, data["url"], data["name"], data["theme"], data["state"], clock.now())
    return f"{ICON} {data['name']} · {'added' if data['state'] == store.ADDED else 'removed'}"


async def source_check(request: Request, data: dict) -> str:
    listed = {each.url for each in await sources_for(request.user.id)}
    there = data["url"] in listed
    return "" if there == (data["state"] == store.ADDED) else "the change didn't save"


async def state(request: Request) -> State:
    stories = await today_stories(request.user.id)
    lines = [f"{news.CARD_NAMES[each.topic]} ({each.topic}): {each.title}" for each in news.in_order(stories)] if stories else ["today's news: not picked yet"]
    lines.append("sources: " + ", ".join(each.name for each in await sources_for(request.user.id)))
    return State("The user's morning news today, a card a story in #news, a line each by its topic (the stories have no numbers)", tuple(lines), "nothing yet")


def actions() -> list:
    topics = tuple(ALL_TOPICS)
    topic_words = "; ".join(f"{each} = {LABELS[each]}" for each in ALL_TOPICS)
    return [
        Action(
            "news_another",
            "One more story from today's morning news, the next best not shown yet, as a new card in #news (\"another one\", \"one more story\", \"anything else in the news?\").",
            (), needs_card=False, run=another, purpose=EACH_DAY, say=("another one",),
        ),
        Action(
            "news_steer",
            "Shape what the morning news picks from now on: \"more like the housing one\" -> like_topic nz_money; \"more like the one "
            "about the water reform\" -> like_words water reform (today's stories are in the state, by topic); \"less AI\" -> less ai; "
            "\"more NZ politics\" -> more nz_politics; \"skip housing tomorrow\" -> skip nz_money, skip_day tomorrow (one day only); "
            "\"more US politics\" -> us more (US politics is not a topic of its own: it is world_politics); as a reply to a story's card, "
            "\"more like this\" -> this like and \"less of this\" -> this less. "
            f"Topics: {topic_words} (housing, house prices, interest rates, the OCR and the economy are nz_money).",
            (
                Field("like_topic", "\"More like\" one of today's stories, named by its topic: the topic (\"more like the housing one\" -> nz_money; \"more like the AI story\" -> ai). Only when a topic itself is said: \"the one about …\" is like_words. Said with \"like\", it is like_topic, never more.", choices=topics),
                Field("like_words", "\"More like\" one of today's stories, named by words of its headline: those words, exactly as said (\"more like the one about the water reform\" -> water reform). \"The one about …\" is always like_words, even when its topic is plain: never like_topic, and never this."),
                Field("like_number", "Only when the user names a story by a number (\"more like 3\" -> 3): they are asked which, by topic.", INTEGER),
                Field("this", "A story pointed at, not named (\"more like this\" -> like; \"less of this\", \"less like this\" -> less): the card the user replied to, which the code knows.", choices=("like", "less")),
                Field("more", "A topic to have more of, said without \"like\" (\"more NZ politics\", \"more AI news\"). Never for \"more like …\", which is like_topic or like_words.", choices=topics),
                Field("less", "A topic to have less of.", choices=topics),
                Field("skip", "A topic to leave out on one day.", choices=topics),
                Field("skip_day", "The day to leave it out, exactly as said (\"tomorrow\", \"Friday\"). Leave out when no day is said."),
                Field("us", "US politics: more (\"more US politics\", \"more on American politics\") or less. Only when US politics is named.", choices=("more", "less")),
            ),
            prepare=steer_card, apply=steer_apply, verify=steer_check, purpose=SET_UP, say=("less AI", "more like the housing one"),
        ),
        Action(
            "news_show",
            "Today's morning news (\"the news\", \"show me today's news\" -> what today), or what it knows about what the user likes in "
            "the news (\"what do you know about my news?\" -> what prefs).",
            (Field("what", "today or prefs.", choices=("today", "prefs"), required=True),),
            needs_card=False, run=show, purpose=SEE, say=("show me today's news",),
        ),
        Action(
            "news_source",
            "Add a news feed (\"add https://example.com/feed.xml to my news, for tech\"), or remove one (\"stop using The Verge\" -> "
            "remove true, name The Verge).",
            (
                Field("remove", "true to remove a source.", BOOLEAN),
                Field("url", "The feed's address, as given."),
                Field("name", "The source's name, as said."),
                Field("topic", "Which topic it is for, when adding.", choices=topics),
            ),
            prepare=source_card, apply=source_apply, verify=source_check, purpose=SET_UP, say=("remove The Verge from my news",),
        ),
    ]


ONLY_FOR = (
    "The user's morning news: today's 7 or 8 news stories, a card each in #news (world and NZ politics, world news, tech, AI, NZ "
    "housing and money). Showing it (\"the news\"), one more story (\"another one\"), and steering what it picks from now on: more "
    "like one of today's stories by its topic or its headline (\"more like the housing one\", \"more like the one about the water "
    "reform\"), or, replying to a story's card, \"more like this\" or \"less of this\"; more or less of a topic (\"less AI\", \"more NZ politics\"), leaving a "
    "topic out on a day (\"skip housing tomorrow\"); what it knows about what they like; adding or removing a news source. Not "
    "a to-do or a reminder (those tasks, even about reading something), not how a story made the user feel (\"that story about "
    "the floods upset me\": the diary's, to keep), and not a question about a news topic itself (chat)."
)
EXAMPLES = ("another one", "more like the housing one", "less AI")
