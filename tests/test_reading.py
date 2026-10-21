"""The morning news (tasks/reading, behind READING_ENABLED, off; Alex, 21 Oct): the daily read and News headlines as one
task. The 5:30 am job reads every feed, Claude picks 7 or 8 (one a topic, then extras) and writes their TL;DRs, the set
is kept; at 6 am the day's stories are one message in #news, an embed each (yesterday's deleted), and round 7's hub has
one line that links to it; steering in words (a story found by Python from its words), another one, sources. No 👍.

Made-up feeds, pages and headlines only: nothing here reaches the network or Claude.
"""
import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import cards, clock, config, database, design, live, scheduler, surface
from core import day as days
from core.actions import PREPARED, Request
from core.errors import UserError
from tasks import reading
from tasks.briefing import embeds
from tasks.reading import news, pick, plain, rules, sources, store
from tasks.reading.news import AI, NZ_MONEY, NZ_POLITICS, TECH, WEBDEV, WORLD, WORLD_POLITICS

UTC = timezone.utc
WORDS = " ".join(["Made-up words about what happened today, set out plainly for a reader."] * 40)  # about 480 words
SECRET = "Zanzibarquill"  # a made-up word only in an article's text: it must reach no log


def article_page(title, body=WORDS, extra=""):
    return f"<html><body><nav>Home Subscribe</nav><article><h1>{title}</h1><p>{body} {SECRET}</p>{extra}</article></body></html>".encode()


def rss(items):
    entries = "".join(
        f"<item><title>{title}</title><link>{link}</link><pubDate>{when}</pubDate><description>A made-up snippet about {title.lower()}.</description>{extra}</item>"
        for title, link, when, extra in items
    )
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>Made-up</title>{entries}</channel></rss>".encode()


# A made-up feed a topic, two headlines each, and one for the wildcard
HEADLINES = {
    WORLD_POLITICS: ["Made-up election called in a northern republic", "Made-up summit ends with a trade pact"],
    NZ_POLITICS: ["Made-up parliament passes the water reform bill", "Made-up minister quits over a funding report"],
    WORLD: ["Made-up earthquake shakes an island chain", "Made-up flood warning for a river delta"],
    TECH: ["Made-up chip maker unveils a faster processor", "Made-up phone recall over battery faults"],
    AI: ["Made-up lab releases an open reasoning model", "Made-up regulator drafts rules for chatbots"],
    NZ_MONEY: ["Made-up Reserve Bank holds the OCR steady", "Made-up house prices slip for a sixth month"],
    WEBDEV: ["Made-up browser ships a major release", "Made-up package registry patches a security hole"],
}


def feed_url(topic):
    return f"https://{topic.replace('_', '-')}.example/rss"


def link(topic, number, day=""):
    return f"https://{topic.replace('_', '-')}.example/story-{number}{day}?utm_source=rss"


def fresh(world, same_links=False):
    """Each feed as it reads this morning: its headlines two hours old, with links of the day (or the same every day)."""
    stamp = (clock.now() - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    day = "" if same_links else f"-{days.today().isoformat()}"
    for topic, titles in HEADLINES.items():
        extra = [("Made-up premium story on mortgage stress", "https://nz-money.example/premium/stress", stamp, "<category>premium</category>")] if topic == NZ_MONEY else []
        world.pages[feed_url(topic)] = rss([(title, link(topic, number, day), stamp, "") for number, title in enumerate(titles)] + extra)
        for number, title in enumerate(titles):
            world.pages.setdefault(link(topic, number, day).split("?")[0], article_page(title))


FEEDS = [sources.Source(f"Made-up {news.LABELS[topic]}", feed_url(topic), topic) for topic in news.ALL_TOPICS]


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"reading": store.MIGRATIONS})
    clock.advance_to(days.at(date(2026, 10, 21) + timedelta(days=21), time(5, 30)))  # a Wednesday
    seen = SimpleNamespace(owner=owner, sent=[], asked=[], pages={}, failing=set(), chosen=None, nexts=None, tldr=None, shuffle=None)
    seen.day = days.today()
    seen.same_links = True  # the first morning's links are the plain ones; later mornings' are the day's
    for topic, titles in HEADLINES.items():
        for number, title in enumerate(titles):
            seen.pages[link(topic, number).split("?")[0]] = article_page(title)

    def get(url):
        if url in seen.failing or url not in seen.pages:
            raise OSError("made-up failure")
        return seen.pages[url]

    async def call_tool(system, user, tools, *, choice, purpose, task="", max_tokens=600):
        seen.asked.append((tools[0]["name"], user))
        if tools[0]["name"] == pick.CHOOSE:
            numbered = [line for line in user.splitlines() if line.startswith("[")]
            count = len(numbered)
            chosen = seen.chosen if seen.chosen is not None else [index + 1 for index, line in enumerate(numbered) if "one-" not in line][: 8]
            return (pick.CHOOSE, {"chosen": chosen, "next": seen.nexts if seen.nexts is not None else list(range(1, count + 1))})
        found = [line[1:line.index("]")] for line in user.splitlines() if line.startswith("[")]
        answers = [{"id": story, "tldr": seen.tldr or f"Made-up TL;DR {story}: what happened and why it matters to you today."} for story in found]
        return (pick.WRITE, {"tldrs": seen.shuffle(answers) if seen.shuffle else answers})

    async def send(channel_id, card, silent=False):
        cards.check(card)
        seen.sent.append(card)
        return len(seen.sent)

    monkeypatch.setattr(sources, "_get", get)
    monkeypatch.setattr(sources, "starter", lambda: list(FEEDS))
    monkeypatch.setattr(pick.llm, "call_tool", call_tool)
    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(plain, "changed", lambda user_id: None)
    live.reset()
    seen.request = lambda text="": Request(owner, 100, text)
    return seen


def morning(world, keep_pages=False):
    if not keep_pages:
        fresh(world, same_links=world.same_links)
        world.same_links = False
    job = SimpleNamespace(user_id=world.owner.id, notes=[])
    from core import scheduler

    original = scheduler.note
    scheduler.note = lambda job, text: job.notes.append(text)
    try:
        run(plain.pick_job(job))
    finally:
        scheduler.note = original
    return job.notes[-1]


def the_set(world):
    found = run(database.run(store.db_news, world.owner.id, world.day))
    return found[0] if found else []


# --- off, and its parts -------------------------------------------------------------------------------------------------
def test_off_unless_switched_on():
    assert config.READING_ENABLED is False and not reading.task.switched_on()


def test_its_actions_and_its_two_jobs():
    assert [each.name for each in plain.actions()] == ["news_another", "news_steer", "news_show", "news_source"]
    assert reading.task.job_handlers() == {plain.PICK_JOB: plain.pick_job, plain.POST_JOB: plain.post_job}
    assert (reading.PICK_DEFAULT.name, reading.PICK_DEFAULT.at) == ("Morning news", time(5, 30))


def test_the_cards_are_a_step_of_the_morning_routine_before_the_briefing(monkeypatch):
    from core import hub

    monkeypatch.setattr(scheduler, "_joins", {})
    reading.task.setup(None)
    from tasks import briefing

    scheduler.join_routine(hub.MORNING, scheduler.handler_name("briefing", briefing.JOB), order=hub.BRIEFING_ORDER, name=hub.MORNING_NAME)
    steps = scheduler.routine_steps(hub.MORNING)
    assert steps.index(scheduler.handler_name("reading", plain.POST_JOB)) < steps.index(scheduler.handler_name("briefing", briefing.JOB))


def test_news_is_its_own_channel_and_listens_there():
    assert reading.task.home == "news" and reading.task.home_examples == ("another one", "less AI")


def test_each_tldr_is_tied_to_its_story_by_its_id_whatever_order_the_answers_come_in(world):
    """Made-up answers in a shuffled order: each TL;DR still sits under its own story (G: the preview's mix-up)."""
    import random

    world.shuffle = lambda answers: random.Random(7).sample(answers, len(answers))
    morning(world)
    for each in the_set(world):
        assert each.tldr.startswith(f"Made-up TL;DR {each.id}:"), (each.title, each.tldr)


def test_a_tldr_set_that_names_a_story_not_given_or_one_twice_is_refused(world, caplog):
    world.shuffle = lambda answers: [answers[0], {**answers[1], "id": answers[0]["id"]}, *answers[2:]]
    with caplog.at_level(logging.WARNING, logger="assistant"):
        morning(world)
    assert not any(each.tldr.startswith("Made-up TL;DR") for each in the_set(world)), "every one is its own snippet"
    assert "the set is refused" in caplog.text


# --- the morning --------------------------------------------------------------------------------------------------------
def test_the_morning_is_one_a_topic_then_an_extra_with_its_tldrs_and_its_own_links(world):
    said = morning(world)
    stories = the_set(world)
    assert said == f"{len(stories)} stories" and 7 <= len(stories) <= 8
    assert [each.topic for each in stories[:6]] == list(news.TOPICS), "one a topic, in the topics' order"
    assert all(len(each.tldr.split()) <= news.TLDR_MOST for each in stories)
    links = {link(topic, number).split("?")[0] for topic in HEADLINES for number in (0, 1)}
    assert all(each.url in links for each in stories), "each link the item's own, the tracking taken off"
    assert [name for name, _ in world.asked] == [pick.CHOOSE, pick.WRITE], "two requests in all"


def test_a_paid_story_never_goes_to_claude(world):
    morning(world)
    choose_turn = world.asked[0][1]
    assert "premium story" not in choose_turn and "Made-up Reserve Bank holds the OCR steady" in choose_turn


def test_a_morning_twice_is_one_set(world):
    morning(world)
    assert morning(world) == "not picked: today's is picked already" and len(world.asked) == 2


def test_a_feed_that_fails_is_skipped_and_noted_and_its_topic_left_out(world):
    fresh(world, same_links=True)
    world.same_links = False
    world.failing.add(feed_url(AI))
    said = morning(world, keep_pages=True)
    assert said.endswith("; 1 feed not read: Made-up AI") and AI not in [each.topic for each in the_set(world)]


def test_a_topic_claude_leaves_out_gets_its_newest_and_more_than_eight_never(world):
    world.chosen = [1, 2, 3, 99, 3]
    morning(world)
    stories = the_set(world)
    assert {each.topic for each in stories} >= set(news.TOPICS) and len(stories) <= 8


def test_a_tldr_over_forty_words_is_cut_and_one_missing_is_the_snippet(world):
    world.tldr = " ".join(["word"] * 60)
    morning(world)
    assert all(len(each.tldr.split()) <= news.TLDR_MOST for each in the_set(world))


NOT_FREE = '<script type="application/ld+json">{"@type": "NewsArticle", "isAccessibleForFree": false}</script>'


def test_a_page_behind_a_paywall_is_dropped_never_summarised_and_its_topic_takes_its_next(world):
    """Alex, 21 Oct: dropped before it is summarised, never from its snippet. The page says so in its JSON-LD, or reads
    as a paywall; the topic's next story takes the slot."""
    fresh(world, same_links=True)
    world.same_links = False
    world.chosen = [7]  # the tech slot's first story, as the pick has the items in its order
    paywalled = link(TECH, 0).split("?")[0]
    world.pages[paywalled] = f"<html><head>{NOT_FREE}</head><body><article><p>{WORDS}</p></article></body></html>".encode()
    world.pages[link(AI, 0).split("?")[0]] = article_page("Made-up lab releases an open reasoning model", WORDS, "<p>Subscribe to continue reading.</p>")
    morning(world, keep_pages=True)
    write_turn = world.asked[1][1]
    stories = the_set(world)
    assert paywalled not in {each.url for each in stories} and "A made-up snippet about made-up chip maker" not in write_turn
    assert "Made-up chip maker unveils" not in write_turn and "Made-up phone recall over battery faults" in write_turn, "the topic's next story"
    assert "Made-up lab releases an open reasoning model" not in write_turn and "Made-up regulator drafts rules for chatbots" in write_turn
    assert [each.topic for each in stories].count(TECH) == 1


def test_a_page_that_fails_to_load_is_summarised_from_its_snippet(world):
    fresh(world, same_links=True)
    world.same_links = False
    world.failing.add(link(TECH, 0).split("?")[0])
    morning(world, keep_pages=True)
    assert "A made-up snippet about made-up chip maker unveils a faster processor." in world.asked[1][1]


def test_one_us_only_politics_story_a_day_unless_he_asks_for_more(world):
    fresh(world, same_links=True)
    world.same_links = False
    stamp = (clock.now() - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    world.pages["https://us-politics.example/rss"] = rss([
        ("Made-up senate vote on a spending bill", "https://us-politics.example/1", stamp, ""),
        ("Made-up governor race tightens in a swing state", "https://us-politics.example/2", stamp, ""),
    ])
    FEEDS.append(sources.Source("Made-up US Politics", "https://us-politics.example/rss", WORLD_POLITICS, "us"))
    try:
        world.chosen = [1, 2, 3, 4, 5, 6, 7, 8]  # the two US ones come first, as the newest
        morning(world, keep_pages=True)
        titles = [each.title for each in the_set(world)]
        assert sum(1 for each in titles if each.startswith(("Made-up senate", "Made-up governor"))) == 1
        steer(world, us="more")
        clock.advance(timedelta(days=1))
        world.day = days.today()
        stamp = (clock.now() - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        world.pages["https://us-politics.example/rss"] = rss([
            ("Made-up house speaker vote fails again", "https://us-politics.example/3", stamp, ""),
            ("Made-up court rules on a state election map", "https://us-politics.example/4", stamp, ""),
        ])
        morning(world)
        titles = [each.title for each in the_set(world)]
        assert sum(1 for each in titles if each.startswith(("Made-up house speaker", "Made-up court rules"))) == 2, "asked for more: two"
        assert "At most 2 stories about US politics alone" in world.asked[2][1]
    finally:
        FEEDS.pop()


def test_nothing_of_an_article_reaches_a_log(world, caplog):
    with caplog.at_level(logging.DEBUG):
        world.failing.add(link(WORLD, 0).split("?")[0])
        morning(world)
    assert SECRET not in caplog.text and "Made-up earthquake" not in caplog.text


def test_on_a_monday_the_window_is_since_saturday_5_30_am(world):
    monday = world.day + timedelta(days=(7 - world.day.weekday()) % 7 or 7)
    clock.advance_to(days.at(monday, time(5, 30)))
    world.day = monday
    saturday = (days.at(monday - timedelta(days=2), time(9, 0))).strftime("%a, %d %b %Y %H:%M:%S +0000")
    fresh(world, same_links=True)
    world.same_links = False
    world.pages[feed_url(WORLD)] = rss([("Made-up weekend storm closes a port", link(WORLD, 5), saturday, "")])
    world.pages[link(WORLD, 5).split("?")[0]] = article_page("Made-up weekend storm closes a port")
    morning(world, keep_pages=True)
    assert "Made-up weekend storm closes a port" in world.asked[0][1]


# --- #news: one message a day --------------------------------------------------------------------------------------
HUB_ID, NEWS_ID = 400, 500


@pytest.fixture
def room(world, monkeypatch):
    """A hub, #news made the first time it is needed, messages that record where they went, deletes that record."""
    world.places, world.made, world.deleted, world.where, world.fail = {HUB_ID: "hub"}, [], [], [], False
    kept = dict(config.CHANNELS)

    def place(channel_id):
        name = world.places.get(channel_id)
        return surface.Place(channel_id, name, f"<#{channel_id}>", True, True) if name else None

    async def make_place(beside, name, reason=""):
        world.made.append((beside, name))
        world.places[NEWS_ID] = name
        return NEWS_ID

    async def send(channel_id, card, silent=False):
        cards.check(card)
        if world.fail:
            raise surface.Failed("made-up failure")
        world.sent.append(card)
        world.where.append(channel_id)
        return 1000 + len(world.sent)

    async def delete(channel_id, message_id):
        world.deleted.append((channel_id, message_id))

    monkeypatch.setattr(surface, "place", place)
    monkeypatch.setattr(surface, "make_place", make_place)
    monkeypatch.setattr(surface, "link", lambda channel_id, message_id: f"https://discord.example/{channel_id}/{message_id}")
    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "delete", delete)
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    monkeypatch.setattr(config, "DESIGN_ROUND", 7)
    config.CHANNELS.pop("news", None)
    config.CHANNELS["hub"] = HUB_ID
    plain._cannot_make.clear()
    yield world
    plain._cannot_make.clear()
    config.CHANNELS.clear()
    config.CHANNELS.update(kept)


def post(world):
    job = SimpleNamespace(user_id=world.owner.id, notes=[])
    original = scheduler.note
    scheduler.note = lambda job, text: job.notes.append(text)
    try:
        run(plain.post_job(job))
    finally:
        scheduler.note = original
    return job.notes[-1]


def test_at_6_am_the_day_s_stories_are_one_message_in_news_made_beside_the_hub_in_the_topics_order(room):
    morning(room)
    assert post(room) == "posted, 8 stories"
    assert room.made == [(HUB_ID, "news")] and room.where == [NEWS_ID] and config.CHANNELS["news"] == NEWS_ID
    (message,) = room.sent
    topics = [each.author.split(" · ")[0] for each in message.embeds]
    assert len(topics) == 8 and topics[0] == "NZ politics"
    order = [news.CARD_NAMES[each] for each in news.CARD_ORDER]
    assert [order.index(each) for each in topics] == sorted(order.index(each) for each in topics), "the fixed topic order"
    assert all(each.status == design.PREPARED and each.url.startswith("https://") and each.description.startswith("Made-up TL;DR") for each in message.embeds)
    assert not message.thumbs_up and "Made-up TL;DR" not in message.text, "no 👍; what is logged is the headlines"


def test_twice_or_after_a_restart_a_day_is_never_posted_again(room):
    morning(room)
    post(room)
    assert post(room) == "posted already" and len(room.sent) == 1


def test_a_message_cut_off_mid_post_by_a_start_is_never_posted_twice(room):
    morning(room)
    run(database.run(store.db_post_sending, room.owner.id, room.day, store.DAY_SLOT, the_set(room), NEWS_ID))  # noted, then cut off
    run(plain.news_channel(room.owner.id))
    assert post(room) == "posted already" and room.sent == []


def test_a_post_that_fails_is_tried_again_and_posts_once(room):
    morning(room)
    room.fail = True
    with pytest.raises(surface.Failed):
        post(room)
    room.fail = False
    assert post(room) == "posted, 8 stories" and len(room.sent) == 1


def test_the_next_morning_yesterday_s_message_is_deleted_first_only_the_bot_s_own(room):
    morning(room)
    post(room)
    run(plain.another(Request(room.owner, NEWS_ID, "another one"), {}, frozenset()))
    clock.advance(timedelta(days=1))
    room.day = days.today()
    morning(room)
    assert post(room) == "posted, 8 stories; 2 of earlier days deleted"
    assert room.deleted == [(NEWS_ID, 1001), (NEWS_ID, 1002)] and len(room.sent) == 3


def test_the_dev_bot_never_makes_news(room, monkeypatch):
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    morning(room)
    assert post(room) == "not posted: there is no #news (the dev bot makes none: NEWS_CHANNEL_ID)" and room.made == [] and room.sent == []


def test_news_that_can_t_be_made_deserves_a_look(room, monkeypatch):
    async def refused(beside, name, reason=""):
        raise surface.Failed("Missing Permissions", 403, 50013)

    monkeypatch.setattr(surface, "make_place", refused)
    morning(room)
    assert post(room) == "not posted: there is no #news"
    (item,) = run(reading.items(room.owner.id, clock.now()))
    assert "#news can't be made" in item.what


def test_news_channel_id_is_used_when_it_is_set(room):
    room.places[600] = "my-news"
    config.CHANNELS["news"] = 600
    morning(room)
    post(room)
    assert room.made == [] and room.where == [600]


def test_the_news_message_is_the_task_s_own_live_message(room):
    morning(room)
    post(room)
    assert run(reading.task.message_class(1001)).name == "LIVE" and run(reading.task.message_class(4)) is None


def test_the_longest_realistic_day_fits_one_message(room):
    """Eight stories, headlines of 200 characters, outlets' long names, TL;DRs of 40 long words: inside 6,000 together."""
    from core.cards import MAX_EMBED_TOTAL, embed_size

    long_tldr = " ".join(["Internationalisation"] * 40)
    stories = [news.Story(f"https://news.example/{number}", f"Made-up {number} " + "headline " * 22, "Made-up Wire of the Long Name and Its Regional Editions", topic, long_tldr)
               for number, topic in enumerate([NZ_POLITICS, NZ_POLITICS, NZ_MONEY, WORLD, WORLD_POLITICS, TECH, AI, WEBDEV])]
    card = news.one_message(stories, room.day)
    cards.check(card)
    assert sum(embed_size(each) for each in card.embeds) <= news.MESSAGE_BUDGET < MAX_EMBED_TOTAL and len(card.embeds) == 8
    assert [each.title for each in card.embeds] == [" ".join(each.title.split()) for each in news.in_order(stories)], "never a headline cut"
    assert any(each.description.endswith("…") for each in card.embeds), "the longest TL;DRs shortened to fit"


# --- the hub: round 7's second message ----------------------------------------------------------------------------------
def test_in_round_7_the_hub_has_one_purple_line_that_links_to_the_news_message(room, monkeypatch):
    morning(room)
    assert run(plain.day_items(room.owner.id, room.day)) == [], "nothing until the message is up"
    post(room)
    monkeypatch.setattr(config, "DESIGN_ROUND", 5)
    assert run(plain.day_items(room.owner.id, room.day)) == []
    monkeypatch.setattr(config, "DESIGN_ROUND", 7)
    (item,) = run(plain.day_items(room.owner.id, room.day))
    card = embeds.everything_else([item])
    cards.check(card)
    (embed,) = card.embeds
    assert (embed.title, embed.url, embed.description, embed.status) == ("📰 8 stories in #news", f"https://discord.example/{NEWS_ID}/1001", "", design.PREPARED)
    assert card.thumbs_up is None, "no 👍 on the hub's line"


def test_message_two_puts_the_news_after_the_to_dos_and_the_diary_and_is_sent_with_it_alone(room):
    from core.actions import TODO, TRACKING, DayItem

    morning(room)
    post(room)
    (item,) = run(plain.day_items(room.owner.id, room.day))
    card = embeds.everything_else([item, DayItem(TODO, "Buy stamps"), DayItem(TRACKING, "Diary · Streak: 3 days", icon="📓")])
    assert [each.status for each in card.embeds] == [design.TODOS, design.TRACKING, design.PREPARED]
    alone = embeds.everything_else([item])
    assert [each.title for each in alone.embeds] == ["📰 8 stories in #news"], "the news's line alone: nothing else in it"


# --- steering in words ------------------------------------------------------------------------------------------------
def steer(world, **data):
    card = run(plain.steer_card(world.request(), data, frozenset()))
    run(plain.steer_apply(world.request(), card.data))
    assert run(plain.steer_check(world.request(), card.data)) == ""
    return card


def test_more_like_the_housing_one_less_ai_and_more_nz_politics_are_kept_and_given_to_every_later_pick(world):
    morning(world)
    housing = next(each for each in the_set(world) if each.topic == NZ_MONEY)
    card = steer(world, story="the Reserve Bank")
    assert card.lines == ("More **NZ housing and money**", f"More like **{housing.title}**")
    third = housing
    steer(world, less=AI)
    steer(world, more=NZ_POLITICS)
    with pytest.raises(UserError, match="already"):
        run(plain.steer_card(world.request(), {}, frozenset()))
    clock.advance(timedelta(days=1))
    world.day = days.today()
    morning(world)
    turn = world.asked[2][1]
    assert "He wants more of:" in turn and "NZ politics" in turn and "He wants less of: AI" in turn and third.title in turn


def test_skip_housing_tomorrow_leaves_it_out_tomorrow_only(world):
    morning(world)
    card = steer(world, skip=NZ_MONEY, skip_day="tomorrow")
    tomorrow = world.day + timedelta(days=1)
    assert card.lines == (f"No **NZ housing and money** on {tomorrow:%a} {tomorrow.day} {tomorrow:%b}",)
    clock.advance(timedelta(days=1))
    world.day = days.today()
    morning(world)
    assert NZ_MONEY not in [each.topic for each in the_set(world)] and "Skip today: NZ housing and money" in world.asked[2][1]
    clock.advance(timedelta(days=1))
    world.day = days.today()
    morning(world)
    assert NZ_MONEY in [each.topic for each in the_set(world)], "one day only"


def test_more_like_the_one_about_words_of_its_headline_is_found_by_python(world):
    morning(world)
    card = run(plain.steer_card(world.request(), {"story": "water reform"}, frozenset()))
    assert card.question is None and card.lines[-1] == "More like **Made-up parliament passes the water reform bill**"
    housing = run(plain.steer_card(world.request(), {"story": "housing"}, frozenset()))
    assert housing.question is None and "More like **Made-up Reserve Bank holds the OCR steady**" in housing.lines, "a topic's name counts"


def test_words_that_name_no_story_or_several_ask_which_listing_today_s(world):
    morning(world)
    none = run(plain.steer_card(world.request(), {"story": "zebra crossing"}, frozenset()))
    assert none.question.text == "Which story? Say a few words of its headline."
    assert none.lines[0].startswith("NZ politics: **Made-up parliament") and len(none.lines) == 8, "today's by topic and headline"
    several = run(plain.steer_card(world.request(), {"story": "made-up"}, frozenset()))
    assert several.question.text == "Which of these?" and len(several.question.choices) == 4
    picked = several.question.choices[0]
    again = run(plain.steer_card(world.request(), picked.data, frozenset()))
    assert again.question is None and again.lines[-1].startswith("More like **"), "a button answers it"
    number = run(plain.steer_card(world.request(), {"story": "3"}, frozenset()))
    assert number.question is not None, "a number names no story: asked"


def test_the_news_names_matching_is_pure_and_ignores_small_words():
    stories = [news.Story("https://a.example/1", "Made-up banks cut fixed mortgage interest rates", "W", NZ_MONEY, "x"),
               news.Story("https://a.example/2", "Made-up parliament passes the water reform bill", "W", NZ_POLITICS, "x"),
               news.Story("https://a.example/3", "Made-up lab releases an open reasoning model", "W", AI, "x")]
    assert news.named(stories, "the one about the interest rates") == [stories[0]]
    assert news.named(stories, "AI") == [stories[2]]
    assert news.named(stories, "the one about the") == []


# --- another one ----------------------------------------------------------------------------------------------------------
def test_another_one_is_its_own_one_story_message_in_news_counted_in_the_hub_s_line(room):
    morning(room)
    post(room)
    shown = {each.url for each in the_set(room)}
    said = run(plain.another(Request(room.owner, 100, "another one"), {}, frozenset()))
    assert said.also == f"📰 One more in #news: https://discord.example/{NEWS_ID}/1002"
    (embed,) = room.sent[-1].embeds
    assert room.where[-1] == NEWS_ID and embed.url not in shown and [name for name, _ in room.asked][-1] == pick.WRITE
    (item,) = run(plain.day_items(room.owner.id, room.day))
    assert item.text == "📰 9 stories in #news" and item.link.endswith("/1001"), "the line still opens the day's message"
    in_news = run(plain.another(Request(room.owner, NEWS_ID, "another one"), {}, frozenset()))
    assert in_news.also == "", "said in #news: the message is the answer"


def test_another_one_with_no_news_is_its_message_where_it_was_asked(room, monkeypatch):
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    morning(room)
    run(plain.another(Request(room.owner, 100, "another one"), {}, frozenset()))
    assert room.where == [100] and len(room.sent[-1].embeds) == 1


def test_another_one_when_there_are_no_more_is_said(world):
    world.nexts = []
    morning(world)
    with pytest.raises(UserError, match="every story"):
        run(plain.another(world.request("another one"), {}, frozenset()))


def test_a_story_shown_is_never_shown_again_for_a_week(world):
    morning(world)
    first = {each.url for each in the_set(world)}
    clock.advance(timedelta(days=1))
    world.day = days.today()
    fresh(world, same_links=True)  # the same stories again the next day
    morning(world, keep_pages=True)
    assert not first & {each.url for each in the_set(world)}


# --- showing it, and what it knows ----------------------------------------------------------------------------------------
def test_the_news_said_anywhere_points_to_its_message_and_what_it_knows_is_said(room):
    assert run(plain.show(room.request(), {"what": "today"}, frozenset())) == "📰 No morning news picked today yet."
    morning(room)
    run(plain.show(room.request(), {"what": "today"}, frozenset()))
    assert len(room.sent[-1].embeds) == 8 and room.sent[-1].embeds[0].status == design.PREPARED, "no #news yet: the message here"
    post(room)
    assert run(plain.show(room.request(), {"what": "today"}, frozenset())) == f"📰 8 stories in #news: https://discord.example/{NEWS_ID}/1002"
    assert run(plain.show(room.request(), {"what": "prefs"}, frozenset())).startswith("📰 Nothing said yet")


def test_extraction_is_told_today_s_stories_by_topic_with_no_numbers(world):
    morning(world)
    state = run(plain.state(world.request()))
    assert state.lines[0] == "NZ politics (nz_politics): Made-up parliament passes the water reform bill" and "no numbers" in state.heading


# --- sources in words -----------------------------------------------------------------------------------------------------
def test_a_source_is_added_for_a_topic_and_removed_by_name(world):
    world.pages["https://extra.example/rss"] = rss([("Made-up extra story", "https://extra.example/1", "Wed, 21 Oct 2026 01:00:00 +0000", "")])
    card = run(plain.source_card(world.request(), {"url": "https://extra.example/rss", "name": "Made-up Extra", "topic": TECH}, frozenset()))
    run(plain.source_apply(world.request(), card.data))
    assert "Made-up Extra" in [each.name for each in run(plain.sources_for(world.owner.id))]
    gone = run(plain.source_card(world.request(), {"remove": True, "name": "Made-up Extra"}, frozenset()))
    run(plain.source_apply(world.request(), gone.data))
    assert "Made-up Extra" not in [each.name for each in run(plain.sources_for(world.owner.id))]
    with pytest.raises(UserError, match="Which topic"):
        run(plain.source_card(world.request(), {"url": "https://extra.example/rss"}, frozenset()))


def test_a_source_added_for_an_old_theme_is_read_as_its_topic(world):
    run(database.run(store.db_set_source, world.owner.id, "https://old.example/rss", "Made-up Old", "programming", store.ADDED, clock.now()))
    old = next(each for each in run(plain.sources_for(world.owner.id)) if each.name == "Made-up Old")
    assert old.theme == WEBDEV


def test_every_source_failing_three_days_running_deserves_a_look(world):
    for ahead in range(3):
        run(database.run(store.db_fetched, world.owner.id, world.day - timedelta(days=ahead), 7, 7))
    (item,) = run(reading.items(world.owner.id, clock.now()))
    assert item.what.startswith("the morning news's sources") and item.ping is False
