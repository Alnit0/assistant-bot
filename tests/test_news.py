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


# --- paid articles, as each feed marks them (21 Oct) ------------------------------------------------------------------------
def test_an_nz_herald_premium_story_is_marked_by_its_link_alone():
    """The NZ Herald's feeds carry no category: a premium story's link has /premium/ (on 21 Oct, 30 of 30 agreed with each
    page's own isAccessibleForFree)."""
    raw = b"""<rss><channel>
    <item><title>Made-up free Herald story</title><link>https://www.nzherald.co.nz/nz/made-up-free-story/ABC123/</link><pubDate>Wed, 21 Oct 2026 01:00:00 +0000</pubDate><description>Free.</description></item>
    <item><title>Made-up premium Herald story</title><link>https://www.nzherald.co.nz/business/made-up-premium-story/premium/DEF456/</link><pubDate>Wed, 21 Oct 2026 01:00:00 +0000</pubDate><description>Paid.</description></item>
    </channel></rss>"""
    free, paid = sources.parse_feed(raw, sources.Source("NZ Herald Business", "x", NZ_MONEY))
    assert (free.paid, paid.paid) == (False, True)
    since = datetime(2026, 10, 20, 1, tzinfo=UTC)
    assert [each.title for each in news.eligible([free, paid], since)] == ["Made-up free Herald story"], "dropped before the pick"


def test_a_newsroom_premium_story_is_marked_by_its_category():
    raw = b"""<rss><channel><item><title>Made-up Newsroom story</title><link>https://newsroom.co.nz/2026/10/21/made-up/</link><category>Politics</category><category>Premium</category><pubDate>Wed, 21 Oct 2026 01:00:00 +0000</pubDate></item></channel></rss>"""
    (found,) = sources.parse_feed(raw, sources.Source("Newsroom", "x", NZ_POLITICS))
    assert found.paid


def test_a_page_says_it_is_not_free_in_its_json_ld():
    paid = b'<html><head><script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":"False"}</script></head><body>x</body></html>'
    free = b'<html><head><script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":true}</script></head><body>x</body></html>'
    assert sources.page_paid(paid) and not sources.page_paid(free) and not sources.page_paid(b"<html>no json-ld</html>")


# --- US-only politics: one a day ---------------------------------------------------------------------------------------
def test_at_most_one_us_only_politics_story_a_day_a_slot_falling_back_to_one_that_is_not():
    items = [
        item("Made-up senate passes a budget bill", WORLD_POLITICS, "Made-up US Politics"),  # 1: US-only
        item("Made-up governor race in a swing state", WORLD_POLITICS),  # 2: named by Claude
        item("Made-up election called in a northern republic", WORLD_POLITICS),  # 3
        *ITEMS[1:6],
    ]
    us = news.us_only(items, named=[2])
    assert us == {1} | {0} if items[0].region else us == {1}
    us = {0, 1}
    picked = news.checked_pick([1, 2, 4, 5, 6, 7, 8], items, us=us)
    assert [index for index in picked if index in us] == [0], "one: the extra that was US-only went"
    picked = news.checked_pick([1, 2, 4, 5, 6, 7, 8], items, us=us, us_most=2)
    assert sorted(index for index in picked if index in us) == [0, 1], "asked for more: two"
    picked = news.checked_pick([4, 5, 6, 7, 8], items, us={0, 1})
    assert items[next(index for index in picked if items[index].theme == WORLD_POLITICS)].title.startswith("Made-up senate"), "a slot left empty takes the topic's first, US or not, within the one"


def test_a_feed_of_us_politics_alone_makes_its_stories_us_only():
    raw = b"""<rss><channel><item><title>Made-up house vote</title><link>https://us.example/1</link><pubDate>Wed, 21 Oct 2026 01:00:00 +0000</pubDate></item></channel></rss>"""
    (found,) = sources.parse_feed(raw, sources.Source("Made-up US Politics", "x", WORLD_POLITICS, "us"))
    assert found.region == "us" and news.us_only([found]) == {0}
    assert {each.name for each in sources.starter() if each.region == "us"} == {"Politico", "NPR Politics", "The Guardian US Politics", "BBC US and Canada"}


def test_more_us_politics_is_a_preference_of_its_own():
    after = news.steered(news.Prefs(), us="more")
    assert after.us_most == 2 and news.changes(news.Prefs(), after) == ["Up to **2** US politics stories a day"]
    assert news.steered(after, us="less").us_most == 1 and news.Prefs.from_dict(after.as_dict()).us == 1


# --- the hierarchy (Alex, 21 Oct: "It's too cluttered in its ordered list layout, it needs more hierarchy") ----------------
def test_a_field_a_topic_in_its_fixed_order_its_headline_a_link_its_tldr_small():
    stories = [story(0, topic=topic) for topic in (WORLD_POLITICS, NZ_POLITICS, WORLD, TECH, AI, NZ_MONEY)]
    found = news.fields(stories)
    assert [name for name, _ in found] == ["NZ politics", "Housing and money", "World news", "World politics", "Tech", "AI"], "no Web dev field: nothing that day"
    headline, tldr = found[0][1].split("\n")
    assert headline.startswith("**[") and headline.endswith(")**") and tldr.startswith("-# ")
    assert not any(any(ord(char) > 0x2000 for char in name) for name, _ in found), "no emoji in a field's name"


def test_a_topic_with_two_stories_has_both_the_bigger_first_a_blank_line_between():
    small = Story("https://news.example/a", "Made-up minister quits", "Wire", NZ_POLITICS, "Words.", outlets=1)
    big = Story("https://news.example/b", "Made-up bill passes", "Wire", NZ_POLITICS, "Words.", outlets=4)
    ((name, value),) = news.fields([small, big])
    assert name == "NZ politics" and value.split("\n\n")[0].startswith("**[Made-up bill passes]") and value.count("\n\n") == 1


def test_the_longest_realistic_day_fits_every_field_and_the_whole_embed():
    """Eight stories (two topics with two), headlines of 110 characters, links of 150, TL;DRs of 40 words."""
    from core.cards import MAX_EMBED_TOTAL, MAX_FIELD_VALUE, Card, Embed, check, embed_size

    topics = [NZ_POLITICS, NZ_POLITICS, NZ_MONEY, WORLD, WORLD, WORLD_POLITICS, TECH, AI]
    longest = [story(number, title_words=25, url_length=150, tldr_words=40, topic=topic) for number, topic in enumerate(topics)]
    found = news.fields(longest, "📰 Morning news")
    assert all(len(value) <= news.FIELD_BUDGET < MAX_FIELD_VALUE for _, value in found)
    assert sum(value.count("**[") for _, value in found) == 8, "every story kept"
    embed = Embed("", "📰 Morning news", "prepared", found)
    assert embed_size(embed) <= news.TOTAL_BUDGET < MAX_EMBED_TOTAL
    check(Card("x", embeds=(embed,)))


def test_even_a_day_far_past_realistic_never_breaks_a_limit():
    from core.cards import Card, Embed, check

    absurd = [story(number, title_words=40, url_length=600, tldr_words=40, topic=topic) for number, topic in enumerate([NZ_POLITICS, NZ_POLITICS, AI, AI, TECH, WORLD, WORLD_POLITICS, NZ_MONEY])]
    check(Card("x", embeds=(Embed("", "📰 Morning news", "prepared", news.fields(absurd, "📰 Morning news")),)))


def test_discord_draws_each_field_full_width():
    from core.cards import Card, Embed
    from interfaces.discord import render

    (drawn,) = render.embeds(Card("x", embeds=(Embed("", "📰 Morning news", "prepared", (("NZ politics", "**[A](https://news.example/a)**\n-# Words."),)),)))
    (field,) = drawn.fields
    assert (field.name, field.value, field.inline) == ("NZ politics", "**[A](https://news.example/a)**\n-# Words.", False)
