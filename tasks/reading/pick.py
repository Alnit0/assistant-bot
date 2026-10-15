import logging

from core import llm
from tasks.reading import rules
from tasks.reading.rules import ABOUT, LABELS, Candidate, Profile

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Claude picks the day's article from a few whose text was read, and writes
# its TL;DR from that text. One request; Python checks what comes back (the
# choice in range, the TL;DR at most three lines) and says nothing of a
# choice it can't use. Claude never sees a headline without its article.
# ---------------------------------------------------------------------------
PURPOSE = "reading"
TOOL = "pick"
WORDS_SHOWN = 450  # of each article, for choosing and for the TL;DR
MAX_TOKENS = 350

SYSTEM = (
    "You choose one article for a person's daily read and write its TL;DR. The person is a working web developer "
    "curious about AI, not a researcher: the read is practical and hands-on, about using AI, programming, and the "
    "significant tech news.\n"
    "- Prefer how-tos, tool tips, worked examples, \"I built X with Y\" write-ups, and plain-English explainers of "
    "significant news. Avoid research papers, maths-heavy or theory-only pieces, and anything without a practical "
    "takeaway; avoid hot takes, listicles, rumours and thin news rewrites too.\n"
    "- Rate every article: difficulty from 1 (beginner) to 5 (research), and practicality from 1 (nothing to use) to 5 "
    "(something to try today). Choose only from those in the range the message gives.\n"
    "- Prefer the day's theme, and what the person said they want more or less of.\n"
    "- The TL;DR is 2 or 3 short lines, each a sentence of at most 20 words on a line of its own, then one last line "
    "that starts \"After reading, you will be able to\". Plain English with no jargon, written only from the article's "
    "text given here: what it shows and why it is worth the time. Never promise what the article does not deliver, "
    "never add facts that are not in the text, and never use clickbait. UK English, no em dashes, no headings.\n"
    "- Call the pick tool with every article's ratings, the article's number and the TL;DR."
)
WANTS = {
    rules.ANOTHER: "The person asked for another one.",
    rules.SHORTER: "The person asked for something shorter than the last one.",
    rules.DEEPER: "The person asked for something deeper: a longer, more thorough piece.",
}


def tool(count: int) -> dict:
    return {
        "name": TOOL,
        "description": "The article chosen, and its TL;DR.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ratings": {
                    "type": "array",
                    "description": "Every article's ratings, one each.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "number": {"type": "integer"},
                            "difficulty": {"type": "integer", "description": "1 beginner to 5 research."},
                            "practicality": {"type": "integer", "description": "1 nothing to use to 5 something to try today."},
                        },
                        "required": ["number", "difficulty", "practicality"],
                    },
                },
                "choice": {"type": "integer", "description": f"The chosen article's number, 1 to {count}."},
                "tldr": {"type": "string", "description": "2 or 3 short lines, one sentence each, separated by line breaks, from the article's text only, then a line starting \"After reading, you will be able to\"."},
            },
            "required": ["ratings", "choice", "tldr"],
        },
    }


def user_turn(found: list[Candidate], theme: str, profile: Profile, kind: str = "", only: list[int] | None = None) -> str:
    low, high, practical = rules.target(profile)
    parts = [
        f"Today's theme: {LABELS[theme]} ({ABOUT[theme]}).",
        f"What the person wants: {rules.guidance(profile)}.",
        f"Choose from difficulty {low} to {high} with practicality {practical} or more.",
    ]
    if only:
        parts.append(f"Of these, only {', '.join(str(each) for each in only)} are in that range: choose one of them.")
    if kind in WANTS:
        parts.append(WANTS[kind])
    for number, each in enumerate(found, start=1):
        words = each.text.split()
        shown = " ".join(words[:WORDS_SHOWN]) + (" …" if len(words) > WORDS_SHOWN else "")
        parts.append(f"[{number}] {each.item.title} · {each.item.source} · {LABELS.get(each.item.theme, each.item.theme)} · {each.minutes} min\n{shown}")
    return "\n\n".join(parts)


def ratings(raw, count: int) -> dict[int, tuple[int, int]]:
    """{article number: (difficulty, practicality)} for the ratings that can be used, each 1 to 5. Pure."""
    found = {}
    for each in (raw or {}).get("ratings") or [] if isinstance(raw, dict) else []:
        if not isinstance(each, dict):
            continue
        number, difficulty, practicality = each.get("number"), each.get("difficulty"), each.get("practicality")
        if all(isinstance(value, int) for value in (number, difficulty, practicality)) and 1 <= number <= count and 1 <= difficulty <= 5 and 1 <= practicality <= 5:
            found[number] = (difficulty, practicality)
    return found


def checked(raw, found: list[Candidate]) -> tuple[Candidate, str, tuple[int, int] | None] | None:
    """The chosen candidate, its TL;DR and its ratings, or None for anything that can't be used. Pure."""
    if not isinstance(raw, dict):
        return None
    choice = raw.get("choice")
    if not isinstance(choice, int) or not 1 <= choice <= len(found):
        return None
    tldr = rules.tidy_tldr(raw.get("tldr"))
    if not tldr:
        return None
    return found[choice - 1], tldr, ratings(raw, len(found)).get(choice)


async def _ask(found: list[Candidate], theme: str, profile: Profile, kind: str, only: list[int] | None = None):
    called = await llm.call_tool(
        [{"type": "text", "text": SYSTEM, "cache_control": llm.CACHED}],
        user_turn(found, theme, profile, kind, only),
        [tool(len(found))],
        choice={"type": "tool", "name": TOOL},
        purpose=PURPOSE,
        task=rules.TASK,
        max_tokens=MAX_TOKENS,
    )
    return called[1] if called else None


async def choose(found: list[Candidate], theme: str, profile: Profile, kind: str = "") -> tuple[Candidate, str, tuple[int, int] | None] | None:
    """The article to show, its TL;DR and its ratings, or None. One request; a second only when the one
    chosen is out of the target while others are in it (they are named, and the choice is from them)."""
    if not found:
        return None
    raw = await _ask(found, theme, profile, kind)
    picked = checked(raw, found)
    if picked is None:
        log.warning("Daily read: the pick came back unusable (%s)", "no tool call" if raw is None else "out of range or empty")
        return None
    rated = ratings(raw, len(found))
    fitting = sorted(number for number, rating in rated.items() if rules.in_target(rating, profile))
    if rated and not rules.in_target(picked[2], profile) and fitting:
        again = checked(await _ask(found, theme, profile, kind, fitting), found)
        if again is not None and rules.in_target(again[2] or rated.get(found.index(again[0]) + 1), profile):
            picked = (again[0], again[1], again[2] or rated.get(found.index(again[0]) + 1))
        else:
            log.info("Daily read: the second pick was out of the target too; the first is kept")
    elif rated and not fitting:
        log.info("Daily read: nothing today was in the target; the closest was picked")
    if not picked[1].splitlines()[-1].startswith(rules.AFTER):
        log.info("Daily read: the TL;DR came without its After reading line")
    return picked
