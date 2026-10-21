import logging
import re
from datetime import date

from core import llm
from tasks.reading import news
from tasks.reading.news import ABOUT, LABELS, TOPICS, WEBDEV

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Claude's two parts of the morning news, a request each (Haiku):
#
#   choose   from the day's headlines and their feed snippets (numbered, with
#            each one's topic and how many outlets carried it), the topic
#            slots, the wildcard's rule and his preferences as plain data:
#            7 or 8 numbers, and the next best ranked for "another one".
#            Python checks the answer (news.checked_pick): only numbers it
#            gave, one a topic where any exist, never more than 8
#   write    a TL;DR of about 30 words each, from each chosen article's text
#            (or its snippet). Python checks each one's length; the link is
#            always the item's own, never a word of Claude's
#
# What an article says goes to Claude here and nowhere else: never a log,
# #bot-log, a notification or the status line.
# ---------------------------------------------------------------------------
PURPOSE = "reading"
CHOOSE, WRITE = "pick_news", "write_tldrs"
NEXT_KEPT = 12  # stories ranked next, for "another one"
TEXT_WORDS = 600  # of each chosen article, for its TL;DR

CHOOSE_SYSTEM = (
    "You choose a person's morning news: 7 or 8 stories from the numbered headlines given, for a busy reader in New "
    "Zealand who wants to know what matters today.\n"
    "- One story for each topic slot that has any headline: " + ", ".join(f"{LABELS[each]} ({ABOUT[each]})" for each in TOPICS) + ". "
    "Never invent a story for a topic with none.\n"
    "- Then 1 or 2 extras for the biggest news of the day, whatever the topic. A headline carried by several outlets is "
    "a sign of big news.\n"
    f"- {LABELS[WEBDEV]} is a wildcard, never a slot: it may be one of the extras only on a day with something notable "
    f"({ABOUT[WEBDEV]}). Most days it is left out.\n"
    "- Prefer real news with substance: what happened, decided or changed. Avoid opinion pieces, live blogs, quizzes, "
    "listicles, rumours, celebrity gossip and sport.\n"
    "- Follow what the person said they want more or less of, and the sets they liked.\n"
    f"- Also rank up to {NEXT_KEPT} more, best first, for when the person asks for another one.\n"
    "- Name every headline, chosen or not, that is about US domestic politics alone (US elections, Congress, the White "
    "House, US parties or courts, with no other country in it): the person wants at most a few of those.\n"
    "- Call the pick_news tool with the numbers."
)
WRITE_SYSTEM = (
    "You write the TL;DR of each news story for a person's morning news. Each is about 30 words, never more than 40: "
    "what happened, and why the person should read it. Write it only from the text given for that story; never add a "
    "fact that is not there, never guess, and never use clickbait. Plain English, UK spelling, one paragraph, no "
    "headings, no em dashes, no links. Call the write_tldrs tool with one TL;DR for each story's number."
)


def choose_tool(count: int) -> dict:
    numbers = {"type": "array", "items": {"type": "integer"}}
    return {
        "name": CHOOSE,
        "description": "The day's stories, and the next best.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chosen": {**numbers, "description": f"7 or 8 headline numbers, 1 to {count}: one a topic slot, then the extras."},
                "next": {**numbers, "description": f"Up to {NEXT_KEPT} more numbers, best first, none of them chosen."},
                "us_only": {**numbers, "description": "Every headline number about US domestic politics alone, chosen or not."},
            },
            "required": ["chosen", "next", "us_only"],
        },
    }


WRITE_TOOL = {
    "name": WRITE,
    "description": "The TL;DR of each story.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tldrs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"number": {"type": "integer"}, "tldr": {"type": "string", "description": "About 30 words, never more than 40."}},
                    "required": ["number", "tldr"],
                },
            }
        },
        "required": ["tldrs"],
    },
}


def choose_turn(items: list, day: date, guidance: str) -> str:
    """The headlines as plain data: the date, what he said, then a numbered line each."""
    lines = [f"Today: {day:%A} {day.day} {day:%B} {day.year}.", f"What the person said: {guidance}", "Headlines:"]
    for number, each in enumerate(items, start=1):
        carried = f" · {each.outlets} outlets" if each.outlets > 1 else ""
        lines.append(f"[{number}] {LABELS.get(each.theme, each.theme)} · {each.source}{carried} · {each.title}" + (f"\n    {each.snippet}" if each.snippet else ""))
    return "\n".join(lines)


def write_turn(found: list[tuple[object, str]]) -> str:
    """Each chosen story's headline and text (its article's, or its snippet), numbered."""
    parts = []
    for number, (item, text) in enumerate(found, start=1):
        words = text.split()
        shown = " ".join(words[:TEXT_WORDS]) + (" …" if len(words) > TEXT_WORDS else "")
        parts.append(f"[{number}] {item.title} · {item.source}\n{shown}")
    return "\n\n".join(parts)


async def choose(items: list, day: date, guidance: str, skipped: frozenset[str] = frozenset(), us_most: int = news.US_MOST) -> tuple[list[int], list[int], set[int]] | None:
    """(the chosen indexes, as Python checked them; the next best, in Claude's order; the US-only ones), or None when no
    usable answer came."""
    if not items:
        return None
    called = await llm.call_tool(
        [{"type": "text", "text": CHOOSE_SYSTEM, "cache_control": llm.CACHED}],
        choose_turn(items, day, guidance),
        [choose_tool(len(items))],
        choice={"type": "tool", "name": CHOOSE},
        purpose=PURPOSE,
        task="reading",
        max_tokens=300,
    )
    if called is None or not isinstance(called[1], dict):
        log.warning("Morning news: the pick came back with no call")
        return None
    us = news.us_only(items, called[1].get("us_only"))
    chosen = news.checked_pick(called[1].get("chosen"), items, skipped, us, us_most)
    if not chosen:
        return None
    nexts = [number - 1 for number in called[1].get("next") or [] if isinstance(number, int) and 1 <= number <= len(items)]
    nexts = [index for index in dict.fromkeys(nexts) if index not in chosen and items[index].theme not in skipped][:NEXT_KEPT]
    return chosen, nexts, us


_LINK = re.compile(r"https?://\S+")


async def write(found: list[tuple[object, str]]) -> list[str]:
    """A TL;DR for each (item, text), in order, as Python checked it; one that came back unusable is its snippet,
    shortened. Never a link: any address in Claude's words is taken out."""
    if not found:
        return []
    called = await llm.call_tool(
        [{"type": "text", "text": WRITE_SYSTEM, "cache_control": llm.CACHED}],
        write_turn(found),
        [WRITE_TOOL],
        choice={"type": "tool", "name": WRITE},
        purpose=PURPOSE,
        task="reading",
        max_tokens=110 * len(found) + 100,
    )
    said: dict[int, str] = {}
    for each in (called[1].get("tldrs") or []) if called and isinstance(called[1], dict) else []:
        if isinstance(each, dict) and isinstance(each.get("number"), int):
            said[each["number"]] = news.checked_tldr(_LINK.sub("", str(each.get("tldr") or "")))
    if called is None:
        log.warning("Morning news: the TL;DRs came back with no call; the snippets stand in")
    return [said.get(number) or news.checked_tldr(" ".join(item.snippet.split()[: news.TLDR_WORDS])) or item.title for number, (item, _) in enumerate(found, start=1)]
