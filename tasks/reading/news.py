import re
import urllib.parse
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta

from core import day as days

# ---------------------------------------------------------------------------
# The morning news (Alex, 21 Oct: the daily read and the planned News
# headlines become one feature, "it makes sense to only have one set of news
# generated"). Pure: the topics and their slots, which feed items may go to
# Claude (the window, paid articles, the same story from several outlets),
# Python's check of Claude's pick and of each TL;DR, and the embed's words.
# No network, no database, no Claude here.
# ---------------------------------------------------------------------------
WORLD_POLITICS, NZ_POLITICS, WORLD, TECH, AI, NZ_MONEY = "world_politics", "nz_politics", "world", "tech", "ai", "nz_money"
WEBDEV = "webdev"  # the wildcard: an extra only on a day with something notable
TOPICS = (WORLD_POLITICS, NZ_POLITICS, WORLD, TECH, AI, NZ_MONEY)  # a slot each, every day one has a story
ALL_TOPICS = (*TOPICS, WEBDEV)
LABELS = {
    WORLD_POLITICS: "World politics", NZ_POLITICS: "NZ politics", WORLD: "World news", TECH: "Tech", AI: "AI",
    NZ_MONEY: "NZ housing and money", WEBDEV: "Web development",
}
# What each topic is, for Claude's pick (and for help)
ABOUT = {
    WORLD_POLITICS: "governments, elections and diplomacy around the world",
    NZ_POLITICS: "New Zealand's government, parliament, parties and policy",
    WORLD: "the significant world news that is not politics",
    TECH: "the significant technology news",
    AI: "AI models, tools, companies and how AI is used",
    NZ_MONEY: "New Zealand house prices, interest rates, the OCR and the economy, as a bank's morning market brief has it",
    WEBDEV: "only something notable: a major framework or browser release, a security hole in a widely used package, a big outage, a notable AI coding tool",
}
# The old daily read's themes, for a source added in words before 21 Oct
FROM_THEME = {"ai": AI, "programming": WEBDEV, "news": TECH}
MAX_STORIES = 8  # one a topic, then 1 or 2 extras (the wildcard is one)
MAX_EXTRAS = 2
# US-only politics (Alex, 21 Oct): one a day at most unless he asks for more in words. A story is US-only when it
# comes from a feed of US politics alone (feeds.json, region us) or Claude names it as about US politics alone
US = "us"
US_MOST = 1
TLDR_WORDS, TLDR_MOST = 30, 40  # about 30, never more than 40
SNIPPET_WORDS = 40  # of each item's feed snippet, for the pick
PER_FEED = 12  # the newest of each feed, for the pick
PER_TOPIC = 35  # the newest of each topic, for the pick: every topic has its share
EMBED_BUDGET = 3800  # characters of the embed's description: well inside Discord's 4096
TITLE_MOST = 110
RUN_AT = time(5, 30)
ICON = "📰"
TITLE = "Morning news"


@dataclass(frozen=True)
class Story:
    """One story of the day's set, as shown: its headline is the link to the article."""

    url: str
    title: str
    source: str
    topic: str
    tldr: str


# --- which items go to Claude ------------------------------------------------------------------------------------
def window_start(now: datetime) -> datetime:
    """Items from this moment on: the last 24 hours, and on a Monday since Saturday 5:30 am."""
    today = days.day_of(now)
    if today.weekday() == 0:
        return days.at(today - timedelta(days=2), RUN_AT)
    return now - timedelta(hours=24)


_TRACKING = re.compile(r"^(utm_[a-z]+|fbclid|gclid|mc_[a-z]+|ref|cmpid|ito|at_[a-z]+)$", re.IGNORECASE)


def clean_url(url: str) -> str:
    """An article's link without tracking parameters or a fragment: shorter, the same page."""
    parts = urllib.parse.urlsplit(url.strip())
    kept = [(key, value) for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(key)]
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(kept), ""))


_STOP = frozenset(
    "the a an and or of to in on for at by with from as is are was were be been it its this that these those after over "
    "into about up out new says say said will would could can has have had not but than more most nz us uk".split()
)


def words_of(title: str) -> frozenset[str]:
    """A headline's telling words: lower case, no punctuation, no little words. For telling stories apart."""
    return frozenset(word for word in re.findall(r"[a-z0-9']+", title.lower().replace("’", "'")) if len(word) > 2 and word not in _STOP)


def same_story(first: frozenset[str], second: frozenset[str]) -> bool:
    """Two headlines about the same thing: most of the shorter one's telling words are in the other."""
    shared = first & second
    return len(shared) >= 3 and len(shared) / max(1, min(len(first), len(second))) >= 0.6


def eligible(items: list, since: datetime, shown: set[str] = frozenset()) -> list:
    """What may go to Claude: from the window on, free to read (a paid one dropped), never shown before, the newest
    PER_FEED of each feed, and the same story from several outlets as one (the first source kept, how many carried
    it counted in `outlets`, a sign of the day's biggest news). Newest first, at most PER_TOPIC a topic."""
    fresh = [each for each in items if each.published is not None and each.published >= since and not each.paid and each.url and each.title]
    fresh = [replace(each, url=clean_url(each.url)) for each in fresh]
    fresh = [each for each in fresh if each.url not in shown]
    by_feed: dict[str, int] = {}
    newest_first = sorted(fresh, key=lambda each: each.published, reverse=True)
    kept = []
    for each in newest_first:
        by_feed[each.source] = by_feed.get(each.source, 0) + 1
        if by_feed[each.source] <= PER_FEED:
            kept.append(each)
    found: list = []
    telling: list[frozenset[str]] = []
    for each in kept:
        mine = words_of(each.title)
        twin = next((index for index, theirs in enumerate(telling) if found[index].url == each.url or same_story(mine, theirs)), None)
        if twin is None:
            found.append(replace(each, outlets=1))
            telling.append(mine)
        else:
            found[twin] = replace(found[twin], outlets=found[twin].outlets + 1)
    count: dict[str, int] = {}
    kept_topics = []
    for each in found:
        count[each.theme] = count.get(each.theme, 0) + 1
        if count[each.theme] <= PER_TOPIC:
            kept_topics.append(each)
    return kept_topics


# --- Python's check of the pick and the TL;DRs ----------------------------------------------------------------------
def us_only(items: list, named=()) -> set[int]:
    """The indexes of the US-only politics stories: from a feed of US politics alone, or named so by Claude (1-based)."""
    found = {index for index, each in enumerate(items) if each.region == US}
    return found | {number - 1 for number in named or [] if isinstance(number, int) and 1 <= number <= len(items)}


def checked_pick(numbers, items: list, skipped: frozenset[str] = frozenset(), us: set[int] = frozenset(), us_most: int = US_MOST) -> list[int]:
    """Claude's chosen item numbers (1-based), made right: only items that were given, each once; one a topic where any
    exist that day (a topic Claude left out gets its first item in the list, the newest; a topic with none, or skipped
    for today, is left out, never padded); then at most MAX_EXTRAS extras, the wildcard only ever as one; MAX_STORIES
    at most; and at most `us_most` US-only politics stories (`us`, 0-based), a slot falling back to the topic's first
    story that is not. In the order the topics come, then the extras. Returns 0-based indexes."""
    asked = [number - 1 for number in (numbers or []) if isinstance(number, int) and 1 <= number <= len(items)]
    asked = list(dict.fromkeys(asked))
    asked = [index for index in asked if items[index].theme not in skipped]
    slots: dict[str, int] = {}
    extras: list[int] = []
    taken = {"us": 0}

    def room(index: int) -> bool:
        return index not in us or taken["us"] < us_most

    for index in asked:
        topic = items[index].theme
        if topic not in ALL_TOPICS or not room(index):
            continue
        if topic in TOPICS and topic not in slots:
            slots[topic] = index
        elif len(extras) < MAX_EXTRAS:
            extras.append(index)
        else:
            continue
        taken["us"] += index in us
    for topic in TOPICS:
        if topic not in slots and topic not in skipped:
            first = next((index for index, each in enumerate(items) if each.theme == topic and room(index) and index not in extras), None)
            if first is not None:
                slots[topic] = first
                taken["us"] += first in us
    chosen = [slots[topic] for topic in TOPICS if topic in slots]
    extras = [index for index in extras if index not in chosen][:MAX_EXTRAS]
    return (chosen + extras)[:MAX_STORIES]


def checked_tldr(text) -> str:
    """A TL;DR as shown: one paragraph, no headings or em dashes, at most TLDR_MOST words (cut at a sentence's end
    where one is near, else with an ellipsis). "" for nothing usable."""
    said = " ".join(str(text or "").replace("—", ",").replace("–", "-").split())
    said = re.sub(r"^(tl;?dr:?\s*)", "", said, flags=re.IGNORECASE).strip(" *#")
    words = said.split()
    if not words:
        return ""
    if len(words) <= TLDR_MOST:
        return said
    cut = " ".join(words[:TLDR_MOST])
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= 0 and len(cut[: end + 1].split()) >= TLDR_WORDS - 8:
        return cut[: end + 1]
    return cut.rstrip(",;:") + "…"


# --- the embed ---------------------------------------------------------------------------------------------------
def _title(title: str) -> str:
    title = " ".join(title.split()).replace("[", "(").replace("]", ")")
    return title if len(title) <= TITLE_MOST else title[: TITLE_MOST - 1].rstrip() + "…"


def story_line(number: int, story: Story, tldr: str | None = None) -> str:
    """ "1. **[Headline](link)** · *NZ politics*" and its TL;DR under it."""
    return f"{number}. **[{_title(story.title)}]({story.url})** · *{LABELS.get(story.topic, story.topic)}*\n{story.tldr if tldr is None else tldr}"


def _short(tldr: str, most: int) -> str:
    words = tldr.split()
    return tldr if len(words) <= most else " ".join(words[:most]).rstrip(",;:.") + "…"


def description(stories: list[Story]) -> str:
    """Every story, numbered 1 to 8, inside EMBED_BUDGET: the TL;DRs are shortened (30 words, then 24) only if the
    whole would not fit, and on a day that still would not, the last stories go."""
    for most in (TLDR_MOST, TLDR_WORDS, 24, 18):
        said = "\n".join(story_line(number, each, _short(each.tldr, most)) for number, each in enumerate(stories, start=1))
        if len(said) <= EMBED_BUDGET:
            return said
    while stories and len(said) > EMBED_BUDGET:
        stories = stories[:-1]
        said = "\n".join(story_line(number, each, _short(each.tldr, 18)) for number, each in enumerate(stories, start=1))
    return said


def plain_text(stories: list[Story], day: date) -> str:
    """The set in words, for the log line of a message and for a copy where embeds are not drawn: headlines only."""
    return "\n".join([f"{ICON} {TITLE} · {day:%a} {day.day} {day:%b}", *(f"{number}. {each.title}" for number, each in enumerate(stories, start=1))])


# --- steering in words (kept in the database, used by every later pick) ------------------------------------------
WEIGHT_MOST = 2  # "more NZ politics" twice is as far as it goes; "less AI" twice the other way
LIKED_KEPT = 8  # stories he asked for more like, the newest kept


@dataclass
class Prefs:
    """What Alex said about the news: more or less of a topic, stories to have more like, and a topic skipped on a day."""

    weights: dict = field(default_factory=dict)  # topic: -2 to 2
    like: list = field(default_factory=list)  # [{"title", "topic"}], newest last
    skips: dict = field(default_factory=dict)  # "2026-10-22": [topic]
    us: int = 0  # "more US politics": one more US-only politics story a day, a time (WEIGHT_MOST at most)

    def as_dict(self) -> dict:
        return {"weights": self.weights, "like": self.like, "skips": self.skips, "us": self.us}

    @property
    def us_most(self) -> int:
        """How many US-only politics stories a day: one, and one more for each time he asked for more."""
        return US_MOST + self.us

    @classmethod
    def from_dict(cls, data: dict | None) -> "Prefs":
        data = data or {}
        weights = {topic: max(-WEIGHT_MOST, min(WEIGHT_MOST, int(value))) for topic, value in (data.get("weights") or {}).items() if topic in ALL_TOPICS}
        skips = {day: [each for each in topics if each in ALL_TOPICS] for day, topics in (data.get("skips") or {}).items()}
        return cls(weights, list(data.get("like") or [])[-LIKED_KEPT:], skips, max(0, min(WEIGHT_MOST, int(data.get("us") or 0))))


def steered(prefs: Prefs, more: str = "", less: str = "", like: Story | None = None, skip: str = "", skip_on: date | None = None, today: date | None = None, us: str = "") -> Prefs:
    """The preferences after what was said. A skip is for one day; skips of days gone by are forgotten."""
    weights = dict(prefs.weights)
    if more in ALL_TOPICS:
        weights[more] = min(WEIGHT_MOST, weights.get(more, 0) + 1)
    if less in ALL_TOPICS:
        weights[less] = max(-WEIGHT_MOST, weights.get(less, 0) - 1)
    liked = list(prefs.like)
    if like is not None:
        liked = [*[each for each in liked if each.get("title") != like.title], {"title": like.title, "topic": like.topic}][-LIKED_KEPT:]
        weights[like.topic] = min(WEIGHT_MOST, weights.get(like.topic, 0) + 1) if like.topic not in (more, less) else weights.get(like.topic, 0)
    skips = {day: list(topics) for day, topics in prefs.skips.items() if today is None or day >= today.isoformat()}
    if skip in ALL_TOPICS and skip_on is not None:
        skips[skip_on.isoformat()] = sorted({*skips.get(skip_on.isoformat(), []), skip})
    us_more = max(0, min(WEIGHT_MOST, prefs.us + (1 if us == "more" else -1 if us == "less" else 0)))
    return Prefs({topic: value for topic, value in weights.items() if value}, liked, skips, us_more)


def skipped_on(prefs: Prefs, day: date) -> frozenset[str]:
    return frozenset(prefs.skips.get(day.isoformat(), []))


def _day_name(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def changes(before: Prefs, after: Prefs) -> list[str]:
    """What a steering card says it will change, a line each, in the task's own words."""
    lines = []
    for topic in ALL_TOPICS:
        was, now = before.weights.get(topic, 0), after.weights.get(topic, 0)
        if now > was:
            lines.append(f"More **{LABELS[topic]}**" + (" (as much as it goes)" if now == WEIGHT_MOST else ""))
        elif now < was:
            lines.append(f"Less **{LABELS[topic]}**" + (" (as little as it goes)" if now == -WEIGHT_MOST else ""))
    if after.us != before.us:
        stories = "story" if after.us_most == 1 else "stories"
        lines.append(f"{'Up to' if after.us > before.us else 'Back to'} **{after.us_most}** US politics {stories} a day")
    for each in after.like:
        if each not in before.like:
            lines.append(f"More like **{each['title']}**")
    for day, topics in sorted(after.skips.items()):
        new = [topic for topic in topics if topic not in before.skips.get(day, [])]
        if new:
            lines.append(f"No **{', '.join(LABELS[each] for each in new)}** on {_day_name(date.fromisoformat(day))}")
    return lines


def guidance(prefs: Prefs, day: date, liked_sets: list[list[str]] = ()) -> str:
    """What Claude is told about his preferences, as plain data."""
    lines = []
    more = [LABELS[topic] for topic, value in prefs.weights.items() if value > 0]
    less = [LABELS[topic] for topic, value in prefs.weights.items() if value < 0]
    if more:
        lines.append("He wants more of: " + ", ".join(more) + " (prefer extras from these).")
    if less:
        lines.append("He wants less of: " + ", ".join(less) + " (keep its one slot, never an extra from it).")
    if prefs.like:
        lines.append("Stories he asked for more like: " + "; ".join(each["title"] for each in prefs.like[-5:]) + ".")
    for headlines in list(liked_sets)[-3:]:
        lines.append("A set he said was good: " + "; ".join(headlines) + ".")
    skipped = skipped_on(prefs, day)
    if skipped:
        lines.append("Skip today: " + ", ".join(LABELS[each] for each in sorted(skipped)) + " (no story from it).")
    lines.append(f"At most {prefs.us_most} {'story' if prefs.us_most == 1 else 'stories'} about US politics alone.")
    return "\n".join(lines)


def profile_text(prefs: Prefs, today: date) -> str:
    """ "What do you know about my news?": the preferences as they stand."""
    lines = [f"{ICON} **{TITLE}** · what you've said"]
    for topic in ALL_TOPICS:
        value = prefs.weights.get(topic, 0)
        if value:
            lines.append(f"{'More' if value > 0 else 'Less'} **{LABELS[topic]}**")
    if prefs.us:
        lines.append(f"Up to **{prefs.us_most}** US politics stories a day")
    lines += [f"More like **{each['title']}**" for each in prefs.like[-3:]]
    lines += [f"No **{', '.join(LABELS[each] for each in topics)}** on {_day_name(date.fromisoformat(day))}" for day, topics in sorted(prefs.skips.items()) if day >= today.isoformat()]
    return "\n".join(lines) if len(lines) > 1 else f"{ICON} Nothing said yet: an even mix of every topic."
