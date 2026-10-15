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
    "You choose one article for a person's daily read and write its TL;DR. The read is for continuing education: "
    "keeping up with using AI, programming, and the significant tech news.\n"
    "- Prefer explainers, tutorials and well-argued deep dives. Avoid hot takes, listicles, rumours and thin news "
    "rewrites; choose them only if nothing else is there.\n"
    "- Prefer the day's theme, and what the person said they want more or less of.\n"
    "- The TL;DR is 2 or 3 short lines, each a sentence of at most 20 words on a line of its own, written only from the article's text given here: what it explains and why "
    "it is worth the time. Make the person want to read it, but never promise what the article does not deliver, "
    "never add facts that are not in the text, and never use clickbait. Plain UK English, no em dashes, no headings.\n"
    "- Call the pick tool with the article's number and the TL;DR."
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
                "choice": {"type": "integer", "description": f"The chosen article's number, 1 to {count}."},
                "tldr": {"type": "string", "description": "2 or 3 short lines, one sentence each, separated by line breaks, from the article's text only."},
            },
            "required": ["choice", "tldr"],
        },
    }


def user_turn(found: list[Candidate], theme: str, profile: Profile, kind: str = "") -> str:
    parts = [f"Today's theme: {LABELS[theme]} ({ABOUT[theme]}).", f"What the person wants: {rules.guidance(profile)}."]
    if kind in WANTS:
        parts.append(WANTS[kind])
    for number, each in enumerate(found, start=1):
        words = each.text.split()
        shown = " ".join(words[:WORDS_SHOWN]) + (" …" if len(words) > WORDS_SHOWN else "")
        parts.append(f"[{number}] {each.item.title} · {each.item.source} · {LABELS.get(each.item.theme, each.item.theme)} · {each.minutes} min\n{shown}")
    return "\n\n".join(parts)


def checked(raw, found: list[Candidate]) -> tuple[Candidate, str] | None:
    """The chosen candidate and its TL;DR, or None for anything that can't be used. Pure."""
    if not isinstance(raw, dict):
        return None
    choice = raw.get("choice")
    if not isinstance(choice, int) or not 1 <= choice <= len(found):
        return None
    tldr = rules.tidy_tldr(raw.get("tldr"))
    if not tldr:
        return None
    return found[choice - 1], tldr


async def choose(found: list[Candidate], theme: str, profile: Profile, kind: str = "") -> tuple[Candidate, str] | None:
    """One request: the article to show and its TL;DR, or None."""
    if not found:
        return None
    called = await llm.call_tool(
        [{"type": "text", "text": SYSTEM, "cache_control": llm.CACHED}],
        user_turn(found, theme, profile, kind),
        [tool(len(found))],
        choice={"type": "tool", "name": TOOL},
        purpose=PURPOSE,
        task=rules.TASK,
        max_tokens=MAX_TOKENS,
    )
    picked = checked(called[1] if called else None, found)
    if picked is None:
        log.warning("Daily read: the pick came back unusable (%s)", "no tool call" if not called else "out of range or empty")
    return picked
