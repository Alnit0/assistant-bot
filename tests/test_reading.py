"""The daily read (tasks/reading, behind READING_ENABLED, off): one article a day, picked from feeds.

Made-up feeds, pages and articles only: nothing here reaches the network or Claude.
"""
import asyncio
import json
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import cards, clock, config, database, live
from core import day as days
from core.actions import Request
from core.errors import UserError
from tasks.reading import pick, plain, rules, sources, store
from tasks.reading.rules import Candidate, Item, Profile

WORDS = " ".join(["Made-up words about building with models, explained step by step."] * 60)  # about 600 words


def article_page(title, body=WORDS, extra=""):
    return f"<html><head><script>var x=1;</script></head><body><nav>Home About Subscribe</nav><article><h1>{title}</h1><p>{body}</p>{extra}</article><footer>Made-up footer</footer></body></html>".encode()


def rss(items):
    entries = "".join(f"<item><title>{title}</title><link>{link}</link><pubDate>{when}</pubDate></item>" for title, link, when in items)
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>Made-up</title>{entries}</channel></rss>".encode()


def atom(items):
    entries = "".join(f"<entry><title>{title}</title><link rel='alternate' href='{link}'/><updated>{when}</updated></entry>" for title, link, when in items)
    return f"<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><title>Made-up</title>{entries}</feed>".encode()


FEEDS = [
    sources.Source("Made-up AI blog", "https://ai.example/feed", rules.AI),
    sources.Source("Made-up code blog", "https://code.example/atom", rules.PROGRAMMING),
    sources.Source("Made-up news", "https://news.example/rss", rules.NEWS),
]


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    from tasks.todos import store as todos_store

    make_db({"reading": store.MIGRATIONS, "todos": todos_store.MIGRATIONS})
    clock.advance_to(days.at(date(2026, 10, 15) + timedelta(days=30), time(5, 30)))
    now = clock.now()
    stamp = now.isoformat()
    seen = SimpleNamespace(owner=owner, sent=[], asked=[], pages={}, failing=set(), choose=1, tldr="Made-up TL;DR line one.\nMade-up line two.")
    seen.pages.update({
        "https://ai.example/feed": rss([("Prompting agents, explained", "https://ai.example/agents", stamp), ("A short AI note", "https://ai.example/short", stamp)]),
        "https://code.example/atom": atom([("A deep dive into CSS grid", "https://code.example/grid", stamp)]),
        "https://news.example/rss": rss([("A big chip story, explained", "https://news.example/chips", stamp), ("Paywalled story", "https://news.example/paid", stamp)]),
        "https://ai.example/agents": article_page("Prompting agents, explained"),
        "https://ai.example/short": article_page("A short AI note", " ".join(["Short made-up note."] * 90)),
        "https://code.example/grid": article_page("A deep dive into CSS grid", WORDS * 4),
        "https://news.example/chips": article_page("A big chip story, explained"),
        "https://news.example/paid": article_page("Paywalled story", WORDS, "<p>Subscribe to continue reading.</p>"),
    })

    def get(url):
        if url in seen.failing or url not in seen.pages:
            raise OSError("made-up failure")
        return seen.pages[url]

    async def call_tool(system, user, tools, *, choice, purpose, task="", max_tokens=600):
        seen.asked.append(user)
        return ("pick", {"choice": seen.choose, "tldr": seen.tldr})

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
    monkeypatch.setattr(config, "TODOS_ENABLED", True)
    plain.register()
    live.reset()
    seen.day = days.today()
    seen.request = lambda text="": Request(owner, 100, text)
    return seen


def picked(world):
    return run(plain.pick_today(world.owner.id, world.day))


# --- off, and the sources ----------------------------------------------------------------------------------------
def test_off_unless_switched_on():
    assert config.READING_ENABLED is False


def test_the_starter_sources_are_a_config_file_each_with_a_theme():
    data = json.loads(sources.FEEDS.read_text(encoding="utf-8"))
    assert len(data["sources"]) >= 9 and {each["theme"] for each in data["sources"]} == set(rules.THEMES)
    assert all(each["url"].startswith("https://") for each in data["sources"])


def test_rss_and_atom_feeds_are_read():
    source = FEEDS[0]
    items = sources.parse_feed(rss([("One", "https://a.example/1", "Thu, 15 Oct 2026 08:00:00 +0000")]), source)
    assert items == [Item("https://a.example/1", "One", "Made-up AI blog", rules.AI, datetime(2026, 10, 15, 8, tzinfo=timezone.utc))]
    items = sources.parse_feed(atom([("Two", "https://a.example/2", "2026-10-15T08:00:00Z")]), source)
    assert items[0].url == "https://a.example/2" and items[0].published.year == 2026
    with pytest.raises(Exception):
        sources.parse_feed(b"<html>not a feed</html>", source)


def test_a_page_is_read_down_to_its_article_text():
    text = sources.page_text(article_page("Made-up title"))
    assert text.startswith("Made-up title") and "var x" not in text and "Home About" not in text and "footer" not in text
    assert rules.readable(text) and rules.minutes(text) == 3


def test_a_paywall_or_a_teaser_is_never_readable():
    assert not rules.readable(sources.page_text(article_page("Paid", WORDS, "<p>Subscribe to continue reading.</p>")))
    assert not rules.readable("A made-up teaser of a few words.")


# --- choosing ----------------------------------------------------------------------------------------------------
def test_a_week_keeps_the_themes_balanced():
    profile, day = Profile(), date(2026, 10, 12)  # a Monday
    shown = []
    for ahead in range(6):
        shown.append(rules.theme_for(day + timedelta(days=ahead), profile, shown))
    assert sorted(shown.count(theme) for theme in rules.THEMES) == [2, 2, 2]


def test_a_weight_shifts_the_balance():
    profile = rules.tuned(Profile(), less_theme=rules.NEWS)
    shown = []
    for ahead in range(7):
        shown.append(rules.theme_for(date(2026, 10, 12) + timedelta(days=ahead), profile, shown))
    assert shown.count(rules.NEWS) < shown.count(rules.AI)


def test_only_new_and_recent_items_once_each():
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    items = [Item("https://x/1", "A", "S", rules.AI, now), Item("https://x/1", "A", "S", rules.AI, now), Item("https://x/2", "B", "S", rules.AI, now - timedelta(days=40)), Item("https://x/3", "C", "S", rules.AI, now)]
    assert [each.url for each in rules.eligible(items, {"https://x/3"}, now)] == ["https://x/1"]


def test_the_days_read_is_picked_from_articles_whose_text_was_read(world):
    read = picked(world)
    assert read is not None and read.day == world.day and read.tldr == world.tldr
    (asked,) = world.asked
    assert "Paywalled story" not in asked, "a paywalled article is never offered"
    assert "Made-up words about building" in asked, "Claude sees the article's text, never a headline alone"
    assert run(store.current(world.owner.id, world.day)) == read


def test_no_text_no_tldr(world):
    world.failing.update({"https://ai.example/agents", "https://ai.example/short", "https://code.example/grid", "https://news.example/chips", "https://news.example/paid"})
    assert picked(world) is None and world.asked == [], "Claude is never asked to write from a headline alone"


def test_a_pick_out_of_range_or_empty_is_not_used():
    found = [Candidate(Item("https://x", "T", "S", rules.AI), WORDS, 3)]
    assert pick.checked({"choice": 2, "tldr": "x"}, found) is None and pick.checked({"choice": 1, "tldr": " "}, found) is None
    assert pick.checked({"choice": 1, "tldr": "One.\nTwo.\nThree.\nFour."}, found)[1] == "One.\nTwo.\nThree."


def test_the_tldr_has_no_em_dash():
    assert "—" not in rules.tidy_tldr("A made-up line — with a dash.")


def test_the_pick_job_runs_once_a_day(world):
    job = SimpleNamespace(id=1, user_id=world.owner.id, payload={}, notes=[])
    from core import scheduler

    noted = []
    original = scheduler.note
    scheduler.note = lambda job, text: noted.append(text)
    try:
        run(plain.pick_job(job))
        run(plain.pick_job(job))
    finally:
        scheduler.note = original
    assert noted[0].startswith("picked: ") and noted[1] == "not picked: today's is picked already" and len(world.asked) == 1


# --- the card ------------------------------------------------------------------------------------------------------
def test_the_card_is_the_link_source_time_and_tldr_with_blurple_thumbs(world):
    read = picked(world)
    shown = plain.card(read)
    cards.check(shown)
    assert f"[{read.title}]({read.url}) · {read.source} · {read.minutes} min" in shown.text
    assert "-# Made-up TL;DR line one." in shown.text
    (row,) = shown.rows
    assert [button.emoji for button in row] == ["👍", "👎"] and {button.style for button in row} == {cards.PRIMARY}


def test_the_overview_line_is_the_theme_and_time():
    read = rules.Read("https://x", "Made-up", "Made-up blog", rules.PROGRAMMING, 7, "x", date(2026, 10, 15))
    assert rules.overview(read) == "Programming · 7 min"


def test_thumbs_down_shapes_the_profile_and_offers_another(world):
    read = picked(world)
    said = run(plain.on_vote(SimpleNamespace(user=world.owner, arg=f"{read.day.isoformat()}:down", update=lambda card: _keep(world, card))))
    assert said == "👎 less like this"
    assert run(database.run(store.db_profile, world.owner.id)).weights[read.theme] < 1.0
    assert [button.label for button in world.updated.rows[0]][-1] == "Another one"


async def _keep(world, card):
    world.updated = card


def test_another_one_is_a_different_article(world):
    first = picked(world)
    second = run(plain.another(world.owner.id))
    assert second.url != first.url and run(store.current(world.owner.id, world.day)) == second


def test_something_shorter_or_deeper(world):
    first = picked(world)
    deeper = run(plain.another(world.owner.id, rules.DEEPER))
    assert deeper.minutes > first.minutes
    with pytest.raises(UserError):
        world.choose = 1
        for _ in range(5):
            run(plain.another(world.owner.id, rules.SHORTER))


# --- words -----------------------------------------------------------------------------------------------------------
def test_save_it_for_later_is_a_card_then_a_to_do_with_the_link(world):
    from tasks.todos import store as todos_store

    read = picked(world)
    proposal = run(plain.save_card(world.request("save it for later"), {}, frozenset()))
    assert proposal.lines[0] == f"📝 **Read: {read.title}** · any day" and read.url in proposal.lines[1]
    assert run(plain.save_apply(world.request(), proposal.data)) == "📝 Saved for later · on your to-dos"
    assert any(read.url in each.text for each in run(todos_store.every(world.owner.id)))
    assert run(plain.save_check(world.request(), proposal.data)) == ""


def test_less_news_and_more_about_agents_are_a_card(world):
    proposal = run(plain.tune_card(world.request(), {"less_theme": "news", "more_topic": "agents", "level": "harder"}, frozenset()))
    assert proposal.lines == ("**Tech news** · less often", "**More about** agents", "**Level** · harder")
    run(plain.tune_apply(world.request(), proposal.data))
    kept = run(database.run(store.db_profile, world.owner.id))
    assert kept.more == ["agents"] and kept.level == 1 and run(plain.tune_check(world.request(), proposal.data)) == ""
    assert "more about agents" in rules.guidance(kept)


def test_what_have_i_read_this_week_and_the_profile(world):
    picked(world)
    said = run(plain.show(world.request(), {"what": "week"}, frozenset()))
    assert said.startswith("📖 **This week** · 1 read · 0 👍")
    assert run(plain.show(world.request(), {"what": "profile"}, frozenset())).startswith("📖 **What you like to read**")


def test_a_source_is_added_only_when_its_feed_works_and_removed_by_name(world):
    world.pages["https://new.example/feed"] = rss([("Made-up", "https://new.example/1", clock.now().isoformat())])
    proposal = run(plain.source_card(world.request(), {"url": "https://new.example/feed", "theme": "programming", "name": "Made-up new"}, frozenset()))
    run(plain.source_apply(world.request(), proposal.data))
    assert "Made-up new" in [each.name for each in run(plain.sources_for(world.owner.id))]
    with pytest.raises(UserError):
        run(plain.source_card(world.request(), {"url": "https://broken.example/feed", "theme": "news"}, frozenset()))
    gone = run(plain.source_card(world.request(), {"remove": True, "name": "Made-up news"}, frozenset()))
    run(plain.source_apply(world.request(), gone.data))
    assert "Made-up news" not in [each.name for each in run(plain.sources_for(world.owner.id))]


# --- failures, the week, the order ----------------------------------------------------------------------------------
def test_one_failing_source_is_quiet_every_source_three_days_is_a_look(world):
    from tasks import reading

    world.failing.add("https://news.example/rss")
    picked(world)
    assert run(reading.items(world.owner.id, clock.now())) == []
    for ahead in (1, 2, 3):
        run(database.run(store.db_fetched, world.owner.id, world.day + timedelta(days=ahead), 3, 3))
    (item,) = run(reading.items(world.owner.id, clock.now()))
    assert item.urgency == "problem" and item.ping is False


def test_the_week_line():
    reads = [rules.Read("https://x/1", "A", "S", rules.AI, 5, "x", date(2026, 10, 12), vote=1), rules.Read("https://x/2", "B", "S", rules.NEWS, 4, "x", date(2026, 10, 13))]
    assert rules.week_line(reads) == "2 read · 1 👍 · AI usage, Tech news"


def test_it_comes_after_the_to_dos():
    from tasks import reading, todos

    assert reading.PLACE > todos.PLACE and reading.ORDER > todos.ORDER
