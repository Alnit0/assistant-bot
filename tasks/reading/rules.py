import re
from dataclasses import dataclass
from datetime import datetime

# ---------------------------------------------------------------------------
# The reading task, pure: what a feed item is, whether a page's text can be
# read (never a paywall), and when every source failing deserves a look. The
# morning news's own rules are tasks/reading/news.py (21 Oct: the daily read's
# one article a day went, and its themes with it but for a source added in
# words before then, read as its topic: news.FROM_THEME).
# ---------------------------------------------------------------------------
TASK = "reading"
THEMES = ("ai", "programming", "news")  # the old daily read's, kept for sources added in words before 21 Oct
MIN_WORDS = 250  # less readable text than this is not an article (a teaser, a paywall, a link post)
FAILED_DAYS = 3  # every source failing this many days running is something to look at
# Words a page shows when its text is behind a paywall or a sign-in: a net for reading pages, never
# for understanding what Alex says
_PAYWALL = re.compile(
    r"(subscribe to (?:continue|read)|this post is for (?:paid )?subscribers|already a subscriber|to continue reading|"
    r"sign in to (?:continue|read)|become a (?:paid )?member to read|unlock this (?:article|story))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Item:
    """One feed item: what a feed says, before its page is read."""

    url: str
    title: str
    source: str
    theme: str  # the morning news's topic (tasks/reading/news.py)
    published: datetime | None = None
    snippet: str = ""  # the feed's own words about it, a few sentences at most
    paid: bool = False  # the feed marks it premium or for subscribers: never picked
    outlets: int = 1  # how many feeds carried the same story (news.eligible)
    region: str = ""  # "us" from a feed of US politics alone (feeds.json)


def paywalled(text: str) -> bool:
    """Whether a page's text reads as a paywall or a sign-in, wherever it is in the page."""
    return bool(_PAYWALL.search(text[:4000] + text[-2000:]))


def readable(text: str) -> bool:
    """Whether a page's text is an article that can be read: long enough, and not a paywall."""
    return len(text.split()) >= MIN_WORDS and not _PAYWALL.search(text[:4000] + text[-2000:])


def all_failed(days_failed: list[bool]) -> bool:
    """Whether every source failed on each of the last FAILED_DAYS days (newest first)."""
    return len(days_failed) >= FAILED_DAYS and all(days_failed[:FAILED_DAYS])
