"""The morning news, pure (tasks/reading/news.py) and its feeds (tasks/reading/sources.py): the window, paid articles
dropped, the same story from several outlets as one, Python's check of the pick and of each TL;DR, and the embed kept
well inside Discord's limit. Made-up headlines and made-up links only."""
from datetime import date, datetime, time, timedelta, timezone

import pytest

from core import day as days
from tasks.reading import news, sources
from tasks.reading.news import AI, NZ_MONEY, NZ_POLITICS, TECH, WEBDEV, WORLD, WORLD_POLITICS, Story
from tasks.reading.rules import Item

UTC = timezone.utc
WEDNESDAY = date(2026, 10, 21)


def at(day, hour, minute=0):
    return days.at(day, time(hour, minute))


def item(title, topic=WORLD, source="Made-up Wire", hours_ago=2, url=None, paid=False, now=None):
    now = now or at(WEDNESDAY, 5, 30)
    return Item(url or f"https://news.example/{abs(hash(title)) % 10**8}", title, source, topic, now - timedelta(hours=hours_ago), "A made-up snippet.", paid)


# --- the window -------------------------------------------------------------------------------------------------------
def test_the_last_24_hours_and_on_a_monday_since_saturday_5_30_am():
    assert news.window_start(at(WEDNESDAY, 5, 30)) == at(WEDNESDAY, 5, 30) - timedelta(hours=24)
    monday = date(2026, 10, 26)
    assert news.window_start(at(monday, 5, 30)) == at(date(2026, 10, 24), 5, 30)


# --- what goes to Claude ----------------------------------------------------------------------------------------------
def test_old_paid_and_shown_items_never_go_to_claude():
    since = at(WEDNESDAY, 5, 30) - timedelta(hours=24)
    kept = news.eligible([
        item("Made-up summit agrees a climate deal at last", hours_ago=2),
        item("Made-up council approves a stadium plan", NZ_POLITICS, hours_ago=30),
        item("Made-up bank cuts its fixed mortgage rates", NZ_MONEY, paid=True),
        item("Made-up phone maker recalls a battery pack", TECH, url="https://news.example/shown"),
    ], since, shown={"https://news.example/shown"})
    assert [each.title for each in kept] == ["Made-up summit agrees a climate deal at last"]


def test_the_same_story_from_several_outlets_is_one_with_its_outlets_counted():
    kept = news.eligible([
        item("Made-up Reserve Bank holds the OCR at 3.5 percent", NZ_MONEY, "Outlet A", hours_ago=1),
        item("Reserve Bank holds OCR at 3.5 percent, made-up economists react", NZ_MONEY, "Outlet B", hours_ago=2),
        item("OCR held at 3.5 percent by the made-up Reserve Bank", NZ_MONEY, "Outlet C", hours_ago=3),
        item("Made-up house prices fall for a sixth month", NZ_MONEY, "Outlet B", hours_ago=4),
    ], at(WEDNESDAY, 5, 30) - timedelta(hours=24))
    assert [(each.source, each.outlets) for each in kept] == [("Outlet A", 3), ("Outlet B", 1)], "the newest kept; three outlets: big news"


def test_tracking_parameters_are_taken_off_a_link():
    assert news.clean_url("https://news.example/story/123?utm_source=rss&utm_medium=feed&id=9#top") == "https://news.example/story/123?id=9"


def test_each_feed_gives_its_newest_and_each_topic_has_its_share():
    many = [item(f"Zq{number}a Zq{number}b Zq{number}c Zq{number}d", TECH, "One Feed", hours_ago=1 + number / 10) for number in range(30)]
    assert len(news.eligible(many, at(WEDNESDAY, 5, 30) - timedelta(hours=24))) == news.PER_FEED


# --- Python's check of the pick -------------------------------------------------------------------------------------------
ITEMS = [
    item("Made-up election called in a European country", WORLD_POLITICS),  # 1
    item("Made-up parliament passes a housing bill", NZ_POLITICS),  # 2
    item("Made-up earthquake shakes a Pacific island", WORLD),  # 3
    item("Made-up chip maker shows a faster processor", TECH),  # 4
    item("Made-up AI lab releases a new model", AI),  # 5
    item("Made-up bank raises its deposit rates", NZ_MONEY),  # 6
    item("Made-up browser ships a big release", WEBDEV),  # 7
    item("Made-up summit ends without a deal", WORLD_POLITICS),  # 8
    item("Made-up minister resigns over a report", NZ_POLITICS),  # 9
]


def test_one_a_topic_then_the_extras_the_wildcard_an_extra():
    assert news.checked_pick([5, 1, 2, 3, 4, 6, 7, 9], ITEMS) == [0, 1, 2, 3, 4, 5, 6, 8], "topics in order, then the extras"


def test_a_topic_claude_left_out_gets_its_newest_and_one_with_nothing_is_never_padded():
    without_ai = [each for each in ITEMS if each.theme != AI]
    picked = news.checked_pick([1, 2, 3], without_ai)
    assert [without_ai[index].theme for index in picked] == [WORLD_POLITICS, NZ_POLITICS, WORLD, TECH, NZ_MONEY], "AI had nothing: left out"


def test_only_given_items_each_once_never_more_than_eight_or_two_extras():
    assert news.checked_pick([99, 0, -1, "3", 3, 3], ITEMS)[:3] == [0, 1, 2]
    assert len(news.checked_pick(list(range(1, 10)), ITEMS)) == 8
    assert len(news.checked_pick([1, 2, 3, 4, 5, 6, 7, 8, 9], ITEMS)) - len(news.TOPICS) <= news.MAX_EXTRAS


def test_a_topic_skipped_for_today_has_no_story():
    picked = news.checked_pick([1, 2, 3, 4, 5, 6], ITEMS, skipped=frozenset({NZ_MONEY}))
    assert NZ_MONEY not in [ITEMS[index].theme for index in picked]


def test_a_tldr_is_at_most_40_words_cut_at_a_sentence_where_it_can_be():
    long = "The made-up council voted to build a stadium. " * 3 + "It will cost a great deal and take years, and the vote was close, with many members against it and a few undecided until the end."
    said = news.checked_tldr("TL;DR: " + long)
    assert len(said.split()) <= news.TLDR_MOST and not said.startswith("TL")
    assert news.checked_tldr("  A short one — with a dash.  ") == "A short one , with a dash."
    assert news.checked_tldr("") == ""


# --- the embed ----------------------------------------------------------------------------------------------------------
def story(number, title_words=12, url_length=150, tldr_words=40, topic=NZ_MONEY):
    title = " ".join(["Made-up"] + ["headline"] * (title_words - 1))[: news.TITLE_MOST + 20]
    url = "https://news.example/" + "a" * (url_length - 21)
    return Story(url, title, "Made-up Wire", topic, " ".join(["word"] * tldr_words))


def test_a_story_reads_headline_link_topic_and_its_tldr():
    line = news.story_line(1, Story("https://news.example/x", "Made-up [bank] holds rates", "Wire", NZ_MONEY, "Rates stay where they are."))
    assert line == "1. **[Made-up (bank) holds rates](https://news.example/x)** · *NZ housing and money*\nRates stay where they are."


def test_the_longest_realistic_day_fits_well_inside_discord_s_limit():
    """Eight stories, headlines of 110 characters, links of 150, TL;DRs of 40 words: inside the budget, every story kept."""
    longest = [story(number, title_words=25, url_length=150, tldr_words=40) for number in range(8)]
    said = news.description(longest)
    assert len(said) <= news.EMBED_BUDGET < 4096 and said.count("**[") == 8
    ordinary = [story(number, title_words=10, url_length=90, tldr_words=30) for number in range(8)]
    assert news.description(ordinary).count("word") == 8 * 30, "an ordinary day: not one word cut"


def test_even_a_day_far_past_realistic_never_goes_over():
    absurd = [story(number, title_words=40, url_length=600, tldr_words=40) for number in range(8)]
    assert len(news.description(absurd)) <= news.EMBED_BUDGET


# --- reading feeds ----------------------------------------------------------------------------------------------------
def test_a_new_zealand_feed_s_own_dates_are_read_in_new_zealand_time():
    assert sources._when("20th Oct 26, 3:59pm") == datetime(2026, 10, 20, 2, 59, tzinfo=UTC)
    assert sources._when("1st Mar 2027, 9:05am") == datetime(2027, 2, 28, 20, 5, tzinfo=UTC)
    assert sources._when("not a date") is None


def test_rss_marks_premium_and_takes_the_snippet():
    raw = b"""<rss><channel><item><title>Made-up free story</title><link>https://news.example/a</link><pubDate>Wed, 21 Oct 2026 01:00:00 +0000</pubDate>
    <description>&lt;p&gt;A made-up &lt;b&gt;snippet&lt;/b&gt; here.&lt;/p&gt;</description></item>
    <item><title>Made-up paid story</title><link>https://news.example/b</link><category>premium</category><pubDate>Wed, 21 Oct 2026 01:00:00 +0000</pubDate></item></channel></rss>"""
    free, paid = sources.parse_feed(raw, sources.Source("Wire", "x", NZ_POLITICS))
    assert (free.paid, free.snippet) == (False, "A made-up snippet here.") and paid.paid


def test_rss_1_0_feeds_are_read_too():
    raw = b"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <item><title>Made-up world story</title><link>https://news.example/c</link><dc:date>2026-10-21T01:00:00Z</dc:date><description>Made-up words.</description></item></rdf:RDF>"""
    (found,) = sources.parse_feed(raw, sources.Source("Wire", "x", WORLD))
    assert (found.title, found.published, found.snippet) == ("Made-up world story", datetime(2026, 10, 21, 1, tzinfo=UTC), "Made-up words.")


def test_the_starter_feeds_cover_every_topic_and_the_wildcard():
    topics = {each.theme for each in sources.starter()}
    assert topics == set(news.ALL_TOPICS) and 30 <= len(sources.starter()) <= 40
    assert sum(1 for each in sources.starter() if each.theme == WEBDEV) in (2, 3)
