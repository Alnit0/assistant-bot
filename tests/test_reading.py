"""The morning news (tasks/reading, behind READING_ENABLED, off; Alex, 21 Oct): the daily read and News headlines as one
task. The 5:30 am job reads every feed, Claude picks 7 or 8 (one a topic, then extras) and writes their TL;DRs, the set
is kept and shown in round 7's hub as one purple embed; 👍 on it, steering in words, another one, sources.

Made-up feeds, pages and headlines only: nothing here reaches the network or Claude.
"""
import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import cards, clock, config, database, design, live, thumbsup
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
    seen = SimpleNamespace(owner=owner, sent=[], asked=[], pages={}, failing=set(), chosen=None, nexts=None, tldr=None)
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
        found = [int(line[1:line.index("]")]) for line in user.splitlines() if line.startswith("[")]
        return (pick.WRITE, {"tldrs": [{"number": number, "tldr": seen.tldr or f"Made-up TL;DR {number}: what happened and why it matters to you today."} for number in found]})

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
    plain.register()
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


def test_its_actions_and_its_one_job():
    assert [each.name for each in plain.actions()] == ["news_another", "news_steer", "news_show", "news_source"]
    assert reading.task.job_handlers() == {plain.PICK_JOB: plain.pick_job}
    assert (reading.PICK_DEFAULT.name, reading.PICK_DEFAULT.at) == ("Morning news", time(5, 30))


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


def test_a_page_behind_a_paywall_falls_back_to_its_snippet(world):
    fresh(world, same_links=True)
    world.same_links = False
    world.pages[link(TECH, 0).split("?")[0]] = article_page("Made-up chip maker unveils a faster processor", WORDS, "<p>Subscribe to continue reading.</p>")
    morning(world, keep_pages=True)
    write_turn = world.asked[1][1]
    assert "A made-up snippet about made-up chip maker" in write_turn


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


# --- the hub: round 7's second message ----------------------------------------------------------------------------------
def test_in_round_7_it_is_one_purple_embed_in_message_two_and_before_it_is_not_in_the_hub(world, monkeypatch):
    morning(world)
    monkeypatch.setattr(config, "DESIGN_ROUND", 5)
    assert run(plain.day_items(world.owner.id, world.day)) == []
    monkeypatch.setattr(config, "DESIGN_ROUND", 7)
    (item,) = run(plain.day_items(world.owner.id, world.day))
    assert item.kind == PREPARED and item.title == "Morning news" and item.text.startswith("1. **[")
    card = embeds.everything_else([item])
    (embed,) = card.embeds
    assert (embed.title, embed.status) == ("📰 Morning news", design.PREPARED) and len(embed.description) <= news.EMBED_BUDGET
    assert design.embed_colour(embed.status) == 0x9B59B6


def test_message_two_puts_the_news_after_the_to_dos_and_the_diary(world, monkeypatch):
    from core.actions import TODO, TRACKING, DayItem

    morning(world)
    monkeypatch.setattr(config, "DESIGN_ROUND", 7)
    (item,) = run(plain.day_items(world.owner.id, world.day))
    card = embeds.everything_else([item, DayItem(TODO, "Buy stamps"), DayItem(TRACKING, "Diary · Streak: 3 days", icon="📓")])
    assert [each.status for each in card.embeds] == [design.TODOS, design.TRACKING, design.PREPARED]


# --- 👍: a good set ----------------------------------------------------------------------------------------------------
def test_thumbs_up_on_the_news_is_a_good_set_kept_for_the_picker_and_undone_by_taking_it_away(world, monkeypatch):
    monkeypatch.setattr(config, "THUMBS_UP", True)
    monkeypatch.setattr(config, "DESIGN_ROUND", 7)
    thumbsup.reset()
    morning(world)
    (item,) = run(plain.day_items(world.owner.id, world.day))
    card = embeds.everything_else([item])
    assert card.thumbs_up.task == "reading" and card.thumbs_up.action == plain.LIKED
    thumbsup.register(777, 100, card.thumbs_up)
    assert run(thumbsup.confirm(777, world.owner)) == "📰 noted: a good set"
    assert run(database.run(store.db_news, world.owner.id, world.day))[1] is True
    assert run(database.run(store.db_liked_sets, world.owner.id)) == [[each.title for each in the_set(world)]]
    run(thumbsup.undo(777, world.owner))
    assert run(database.run(store.db_news, world.owner.id, world.day))[1] is False
    thumbsup.reset()


def test_a_liked_set_is_given_to_the_next_morning_s_pick(world):
    morning(world)
    run(database.run(store.db_like_news, world.owner.id, world.day, True))
    clock.advance(timedelta(days=1))
    world.day = days.today()
    morning(world)
    assert "A set he said was good:" in world.asked[2][1]


# --- steering in words ------------------------------------------------------------------------------------------------
def steer(world, **data):
    card = run(plain.steer_card(world.request(), data, frozenset()))
    run(plain.steer_apply(world.request(), card.data))
    assert run(plain.steer_check(world.request(), card.data)) == ""
    return card


def test_more_like_3_less_ai_and_more_nz_politics_are_kept_and_given_to_every_later_pick(world):
    morning(world)
    third = the_set(world)[2]
    card = steer(world, like=3)
    assert card.lines == (f"More **{news.LABELS[third.topic]}**", f"More like **{third.title}**")
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


def test_more_like_a_story_that_is_not_there_is_said(world):
    morning(world)
    with pytest.raises(UserError, match="no story 12"):
        run(plain.steer_card(world.request(), {"like": 12}, frozenset()))


# --- another one ----------------------------------------------------------------------------------------------------------
def test_another_one_is_the_next_best_not_shown_its_tldr_written_now_as_a_reply(world):
    morning(world)
    shown = {each.url for each in the_set(world)}
    said = run(plain.another(world.request("another one"), {}, frozenset()))
    assert said.startswith(f"{len(shown) + 1}. **[") and not any(url in said for url in shown)
    assert [name for name, _ in world.asked][-1] == pick.WRITE


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
def test_the_news_said_anywhere_is_its_embed_and_what_it_knows_is_said(world):
    assert run(plain.show(world.request(), {"what": "today"}, frozenset())) == "📰 No morning news picked today yet."
    morning(world)
    run(plain.show(world.request(), {"what": "today"}, frozenset()))
    assert world.sent[-1].embeds[0].status == design.PREPARED
    assert run(plain.show(world.request(), {"what": "prefs"}, frozenset())).startswith("📰 Nothing said yet")


def test_extraction_is_told_today_s_stories_by_number(world):
    morning(world)
    state = run(plain.state(world.request()))
    assert state.lines[0].startswith("story 1: ") and "(World politics)" in state.lines[0]


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
