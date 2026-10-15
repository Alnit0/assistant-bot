import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

from core import design

# ---------------------------------------------------------------------------
# The daily read, pure: the themes and how a week keeps them balanced, which
# feed items may be picked, the reading time, the interest profile and how
# votes and words shape it, and every line the task says. No network, no
# database, no Claude here.
# ---------------------------------------------------------------------------
TASK, ICON, TITLE = "reading", "📖", "Daily read"
AI, PROGRAMMING, NEWS = "ai", "programming", "news"
THEMES = (AI, PROGRAMMING, NEWS)
LABELS = {AI: "AI usage", PROGRAMMING: "Programming", NEWS: "Tech news"}
# What each theme is, for Claude choosing among candidates (and for help)
ABOUT = {
    AI: "practical use of AI tools, prompting, agents, how people build with models",
    PROGRAMMING: "tutorials, deep dives, techniques, web development",
    NEWS: "the significant tech stories, explained",
}
ANOTHER, SHORTER, DEEPER = "another", "shorter", "deeper"
KINDS = (ANOTHER, SHORTER, DEEPER)
HARDER, EASIER, PRACTICAL = "harder", "easier", "more_practical"
# Who it is for (Alex, 16 Oct: "very academic, maybe too high level"): a working web developer curious about AI.
# Every candidate is rated 1 (beginner) to 5 (research) for difficulty and 1 to 5 for practicality; the pick is
# from DIFFICULTY (moved one either way by "easier" or "harder") with practicality PRACTICAL_MIN or more (5 after
# "more practical"). Both ratings are kept with the read, so feedback can move the target later
DIFFICULTY = (2, 3)
PRACTICAL_MIN = 4
AFTER = "After reading, you will be able to"
WORDS_A_MINUTE = 230
MIN_WORDS = 250  # less readable text than this is not an article (a teaser, a paywall, a link post)
CANDIDATES = 5  # how many articles Claude chooses among
FRESH_FOR = timedelta(days=14)  # an item older than this is not picked
WEIGHT_STEP, WEIGHT_MIN, WEIGHT_MAX = 1.15, 0.5, 2.0
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
    theme: str
    published: datetime | None = None


@dataclass(frozen=True)
class Candidate:
    item: Item
    text: str  # the article's readable text, cut short for Claude
    minutes: int


@dataclass(frozen=True)
class Read:
    """The day's read as shown."""

    url: str
    title: str
    source: str
    theme: str
    minutes: int
    tldr: str
    day: date
    vote: int = 0  # 1 thumbed up, -1 down, 0 neither
    saved: bool = False
    difficulty: int | None = None  # Claude's rating when it was picked: 1 beginner to 5 research
    practicality: int | None = None  # 1 to 5


@dataclass
class Profile:
    """What Alex wants more or less of: a weight a theme, topics, and how hard."""

    weights: dict = field(default_factory=lambda: {theme: 1.0 for theme in THEMES})
    more: list = field(default_factory=list)  # topics: "agents"
    less: list = field(default_factory=list)
    level: int = 0  # -1 easier, 0 as it comes, 1 harder
    practical: int = 0  # 1 after "more practical": practicality 5 only

    def as_dict(self) -> dict:
        return {"weights": self.weights, "more": self.more, "less": self.less, "level": self.level, "practical": self.practical}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Profile":
        if not data:
            return cls()
        weights = {theme: float((data.get("weights") or {}).get(theme, 1.0)) for theme in THEMES}
        return cls(weights, list(data.get("more") or []), list(data.get("less") or []), int(data.get("level") or 0), int(data.get("practical") or 0))


# --- which theme today ----------------------------------------------------------------------------------------
def theme_for(day: date, profile: Profile, shown: list[str]) -> str:
    """Today's theme: the one furthest behind its share of the week so far (its weight), so a
    week stays balanced; ties go round by the day of the week. `shown` is this week's themes."""
    start = day.weekday() % len(THEMES)
    turn = THEMES[start:] + THEMES[:start]
    return min(turn, key=lambda theme: (shown.count(theme) / max(profile.weights.get(theme, 1.0), 0.01), turn.index(theme)))


# --- which items may be picked ---------------------------------------------------------------------------------
def minutes(text: str) -> int:
    return max(1, round(len(text.split()) / WORDS_A_MINUTE))


def readable(text: str) -> bool:
    """Whether a page's text is an article that can be read: long enough, and not a paywall."""
    return len(text.split()) >= MIN_WORDS and not _PAYWALL.search(text[:4000] + text[-2000:])


def eligible(items: list[Item], seen: set[str], now: datetime) -> list[Item]:
    """New items: never shown before, not too old, each once, newest first."""
    fresh = [each for each in items if each.url and each.url not in seen and (each.published is None or now - each.published <= FRESH_FOR)]
    unique = {each.url: each for each in fresh}
    return sorted(unique.values(), key=lambda each: each.published or datetime.min.replace(tzinfo=now.tzinfo), reverse=True)


def for_theme(items: list[Item], theme: str) -> list[Item]:
    """The items to read for a theme: its own first, then the rest (a theme with nothing new is not a day without a read)."""
    return [*(each for each in items if each.theme == theme), *(each for each in items if each.theme != theme)]


def fits(candidate: Candidate, kind: str, current: int | None) -> bool:
    """Whether an article fits "something shorter" or "something deeper" than the one shown."""
    if kind == SHORTER and current is not None:
        return candidate.minutes < current
    if kind == DEEPER and current is not None:
        return candidate.minutes > current
    return True


# --- the profile -------------------------------------------------------------------------------------------------
def voted(profile: Profile, theme: str, up: bool) -> Profile:
    """👍 or 👎 on a read: its theme's weight a step up or down, within bounds."""
    weights = dict(profile.weights)
    weight = weights.get(theme, 1.0) * (WEIGHT_STEP if up else 1 / WEIGHT_STEP)
    weights[theme] = round(min(WEIGHT_MAX, max(WEIGHT_MIN, weight)), 3)
    return replace(profile, weights=weights)


def tuned(profile: Profile, more_theme: str = "", less_theme: str = "", more_topic: str = "", less_topic: str = "", level: str = "") -> Profile:
    """Words: "more about agents", "less news", "harder"."""
    if more_theme in THEMES:
        profile = voted(voted(profile, more_theme, True), more_theme, True)
    if less_theme in THEMES:
        profile = voted(voted(profile, less_theme, False), less_theme, False)
    more, less = list(profile.more), list(profile.less)
    if more_topic:
        topic = more_topic.strip().lower()
        more = [*(each for each in more if each != topic), topic][-8:]
        less = [each for each in less if each != topic]
    if less_topic:
        topic = less_topic.strip().lower()
        less = [*(each for each in less if each != topic), topic][-8:]
        more = [each for each in more if each != topic]
    shift = {HARDER: 1, EASIER: -1}.get(level, 0)
    practical = 1 if level == PRACTICAL else profile.practical
    return replace(profile, more=more, less=less, level=max(-1, min(1, profile.level + shift)), practical=practical)


def target(profile: Profile) -> tuple[int, int, int]:
    """(lowest difficulty, highest, lowest practicality) the pick is made from."""
    low, high = DIFFICULTY
    return max(1, low + profile.level), min(5, high + profile.level), 5 if profile.practical else PRACTICAL_MIN


def in_target(rating: tuple[int, int] | None, profile: Profile) -> bool:
    low, high, practical = target(profile)
    return rating is not None and low <= rating[0] <= high and rating[1] >= practical


def changes(before: Profile, after: Profile) -> list[str]:
    """The card's lines: what a change to the profile does, in words."""
    lines = []
    for theme in THEMES:
        old, new = before.weights.get(theme, 1.0), after.weights.get(theme, 1.0)
        if new != old:
            lines.append(f"**{LABELS[theme]}** · {'more' if new > old else 'less'} often")
    lines += [f"**More about** {topic}" for topic in after.more if topic not in before.more]
    lines += [f"**Less about** {topic}" for topic in after.less if topic not in before.less]
    if after.level != before.level:
        lines.append(f"**Level** · {level_word(after.level)}")
    return lines


def level_word(level: int) -> str:
    return {-1: "easier", 0: "as it comes", 1: "harder"}[level]


def profile_text(profile: Profile) -> str:
    """ "what do you know about what I like to read?" """
    total = sum(profile.weights.values()) or 1
    lines = [f"{ICON} **What you like to read**"]
    lines += [f"**{LABELS[theme]}** · about {round(profile.weights[theme] / total * 7)} days a week" for theme in THEMES]
    if profile.more:
        lines.append("More about: " + ", ".join(profile.more))
    if profile.less:
        lines.append("Less about: " + ", ".join(profile.less))
    lines.append(design.small(f"level: {level_word(profile.level)} · shaped by 👍, 👎 and what you say"))
    return "\n".join(lines)


def guidance(profile: Profile) -> str:
    """What Claude is told of the profile when it chooses."""
    parts = []
    if profile.more:
        parts.append("more about " + ", ".join(profile.more))
    if profile.less:
        parts.append("less about " + ", ".join(profile.less))
    if profile.level:
        parts.append("prefer " + ("harder, more technical" if profile.level > 0 else "easier, more introductory") + " pieces")
    if profile.practical:
        parts.append("only the most practical pieces")
    return "; ".join(parts) or "nothing more yet"


# --- lines and cards ---------------------------------------------------------------------------------------------
VOTE, ANOTHER_BUTTON = "vote", "another"


def headline(read: Read) -> str:
    """ "📖 [Title](link) · Source · 6 min" """
    return f"{ICON} [{read.title}]({read.url}) · {read.source} · {read.minutes} min"


def vote_note(read: Read) -> str:
    return {1: "👍 more like this", -1: "👎 less like this"}.get(read.vote, "")


def card_text(read: Read) -> str:
    lines = [f"### {ICON} {TITLE} · {LABELS.get(read.theme, read.theme)}", headline(read), *(design.small(line) for line in read.tldr.splitlines() if line.strip())]
    if read.vote:
        lines.append(design.small(vote_note(read)))
    return "\n".join(lines)


def overview(read: Read) -> str:
    """Round 5's overview line: what kind of read and how long; the card has the rest."""
    return f"{LABELS.get(read.theme, read.theme)} · {read.minutes} min"


def week_line(reads: list[Read]) -> str:
    """For the week of everything: "5 read · 3 👍 · AI usage, Programming" """
    up = sum(1 for each in reads if each.vote > 0)
    themes = [LABELS[theme] for theme in THEMES if any(each.theme == theme for each in reads)]
    return f"{len(reads)} read · {up} 👍" + (f" · {', '.join(themes)}" if themes else "")


def week_answer(reads: list[Read]) -> str:
    """ "what have I read this week?" """
    if not reads:
        return f"{ICON} Nothing read this week yet."
    lines = [f"{ICON} **This week** · {week_line(reads)}"]
    for each in sorted(reads, key=lambda read: read.day):
        mark = {1: " · 👍", -1: " · 👎"}.get(each.vote, "") + (" · saved" if each.saved else "")
        lines.append(f"`{each.day:%a}` [{each.title}]({each.url}) · {each.source} · {each.minutes} min{mark}")
    return "\n".join(lines)


def all_failed(days_failed: list[bool]) -> bool:
    """Whether every source failed on each of the last FAILED_DAYS days (newest first)."""
    return len(days_failed) >= FAILED_DAYS and all(days_failed[:FAILED_DAYS])


def tidy_tldr(text: str) -> str:
    """Claude's TL;DR as said: at most three lines, then its "After reading, you will be able to …" line;
    no em dashes, no headings. A last line that is missing is not made up here."""
    lines = [re.sub(r"^[#>*\-\s]+", "", line).strip() for line in str(text or "").replace("—", ",").replace("–", "-").splitlines()]
    lines = [line for line in lines if line]
    after = next((line for line in reversed(lines) if line.startswith(AFTER)), "")
    body = [line for line in lines if line != after][:3]
    return "\n".join(body)[:420] + (f"\n{after[:160]}" if after and body else "")
