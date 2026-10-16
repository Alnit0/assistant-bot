import logging
import re
from dataclasses import dataclass

from core import actions, costs, llm, names
from core.actions import Entry

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The router: one small request that says which task a message is for.
#
# It sees the message, what is on screen (an open card, the last couple of
# exchanges) and a catalogue: each task's name, what it is only for, and a
# few example phrases. It never sees an action or a schema, so it costs the
# same however many tasks there are. It answers by calling one tool, which
# code checks: a task it names that isn't in the catalogue is dropped.
#
#   one task (or several, each wanted)   -> extraction for each
#   a genuine tie between tasks          -> buttons naming them
#   not for any task                     -> chat: a plain reply, no tools
#   a task, and a part for no task too   -> both: every part of a message is
#                                           dealt with ("what's the capital of
#                                           France, and add milk")
# ---------------------------------------------------------------------------
TOOL = "route"
HIGH, TIE = "high", "tie"
TASK, CHAT, NOTHING = "task", "chat", "nothing"
MAX_TOKENS = 200
EXCHANGES = 2  # how many recent exchanges it is shown

RULES = (
    "You route one message from the user of a personal assistant bot to the task it is for. "
    "You do not answer the message and you do not act on it: you only call the `route` tool.\n"
    "- Route by meaning, not by keywords. A task's own word in the message (\"pill\", \"timer\") is a hint, "
    "never a switch: \"add my pills to my reminders\" is about reminders.\n"
    "- Read each task's \"only for\" line: it says what the task is for and what it is not.\n"
    "- If the message is for one task, give that task with confidence high.\n"
    "- If the message asks for things from several tasks, give each of them, with confidence high.\n"
    "- If two tasks fit, give the likelier one alone with confidence high whenever one is clearly ahead "
    "(the wording, what is on screen, the recent exchanges). Only when it is a genuine tie give both "
    "with confidence tie: the user is then asked which. A bare request that names no task (\"add X\") "
    "where X could just as well belong to either is a genuine tie: do not settle it by which seems "
    "more usual.\n"
    "- If it is not for any task (a general question, conversation, something no task here does) give "
    "kind chat with no tasks.\n"
    "- The bot replies in words only to questions and requests. If the message asks nothing and needs "
    "nothing done, give kind nothing with no tasks: the bot then says nothing at all. That is a note the "
    "user is leaving for themselves (\"note one\", \"scrap\", \"old news\"), a thank-you, an \"ok\", "
    "and any remark, opinion or statement that asks for nothing (\"shopping is boring\", \"that was "
    "quick\"), even when it mentions something a task deals with. Do not offer help in "
    "return for a remark. A question, or anything that asks the bot to do or say something, is never "
    "nothing: something phrased as a question gets an answer, however idle it seems (\"is shopping "
    "boring for everyone?\" is chat).\n"
    "- Anything about the user's own data goes to the task that owns it, a question included: what is on "
    "a list, which pills they take, what timers are running, which bugs are open. Never chat for these: "
    "chat cannot see any of the user's data.\n"
    "- A destination the user names decides it: \"to my pills\", \"on the shopping list\", \"to the "
    "packing list\" is that task, whatever else the message mentions and whatever is on screen.\n"
    "- A message can hold both: a request for a task and, beside it, a general question or remark that "
    "is for no task (\"what's the capital of France, and add milk to the shopping list\"). Then give "
    "the task as usual and copy the part that is for no task into chat_part, word for word. Every part "
    "of a message must be dealt with. Leave chat_part empty when the whole message is for the task(s); "
    "a greeting or a please is not a part.\n"
    "- A reply to what is on screen usually belongs to the same task as that.\n"
    "- A message that says the user did, took or finished something, or when something happened (\"I took "
    "it at 9pm\", \"I had it at 9\", \"it was 9pm actually\", \"done my stretches\") is a report: set "
    "reports_doing to true. A report is for the task that keeps track of that thing (taking a pill is "
    "pills'), and for the task that answered last in the recent exchanges when it names nothing (\"it\"). "
    "It is never chat: chat can record nothing, and an answer from it would look as if it had. If no "
    "task here keeps track of it (\"I walked the dog at 6\", \"finished my book last night\"), give no tasks "
    "and still set reports_doing to true, whatever the kind: the user is then told it can't be logged, so it "
    "is not a remark to pass over in silence. An opinion, a feeling or a thank-you (\"shopping is boring\", "
    "\"thanks\") reports nothing done.\n"
    "- Set several to true when the message holds two or more separate things to deal with, each a request or a note "
    "of its own, for different tasks or the same one (\"renew rego by Friday, call Mum Sunday 2pm, need milk\", "
    "\"dentist Thursday 3pm and remind me to call the bank at 9\"); give every task they are for. It is false for one "
    "request, however many items it lists for one list (\"add milk, eggs and bread\"), and for a question: a question "
    "is never one of the things, and a message that only asks is never several."
)


# Said only when a task keeps a kind of statement (Entry.keeps): with none, the prompt is as it was
KEEPS = (
    "- A task with a \"Keeps\" line below keeps that kind of statement even though it asks for nothing. A "
    "message that is only that kind of statement is that task's, kind task with confidence high, never nothing, "
    "however short (\"I'm tired\"): "
    "the rule on remarks gives way to it. A remark of any other kind (about the bot, a list, the weather) is "
    "still nothing."
)


@dataclass(frozen=True)
class Route:
    tasks: tuple[str, ...] = ()  # the tasks to hand the message to, likeliest first
    tie: bool = False  # the user must say which of `tasks` they mean
    problem: str = ""  # what was wrong with what the router returned, if anything
    # With tasks: the part of the message that is for none of them (a general
    # question beside the request), to be answered as chat as well
    chat_part: str = ""
    # The message asks nothing and needs nothing done: no reply at all
    nothing: bool = False
    # The message says the user did or took something, or when something happened.
    # With no task to take it, it is neither chat nor silence: the bot says it didn't understand
    reports: bool = False
    # The message holds two or more separate things to deal with: the smart inbox sorts them onto one card
    # (core/smartinbox.py). An answer recorded before the router was asked this says nothing, so False
    several: bool = False

    @property
    def chat(self) -> bool:
        return not self.tasks and not self.nothing


def catalogue_text(entries: list[Entry]) -> str:
    """The tasks as the router reads them. Fixed text for a given set of tasks."""
    lines = ["The tasks:"]
    for entry in entries:
        examples = "; ".join(f"\"{example}\"" for example in entry.examples)
        keeps = f" Keeps: {entry.keeps}" if entry.keeps else ""
        lines.append(f"- {entry.name}: {entry.only_for} For example: {examples}{keeps}")
    return "\n".join(lines)


def system_blocks(entries: list[Entry]) -> list[dict]:
    """The router's instructions and the catalogue: one block, the same for every
    message, marked for caching."""
    rules = f"{RULES}\n{KEEPS}" if any(entry.keeps for entry in entries) else RULES
    return [{"type": "text", "text": f"{rules}\n\n{catalogue_text(entries)}", "cache_control": llm.CACHED}]


def tool(entries: list[Entry]) -> dict:
    return {
        "name": TOOL,
        "description": "Say which task or tasks the message is for, or that it is for none.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": [TASK, CHAT, NOTHING],
                    "description": "chat if it is for no task; nothing if it calls for no answer at all.",
                },
                "tasks": {
                    "type": "array",
                    "items": {"type": "string", "enum": [entry.name for entry in entries]},
                    "description": "The task or tasks it is for. Empty for chat.",
                },
                "confidence": {
                    "type": "string",
                    "enum": [HIGH, TIE],
                    "description": "tie only when two or more tasks fit equally and nothing settles it.",
                },
                "reports_doing": {
                    "type": "boolean",
                    "description": (
                        "true if the message says the user did, took or finished something, or when something "
                        "happened, whether or not any task keeps track of it. Such a message is never "
                        "answered by chat."
                    ),
                },
                "several": {
                    "type": "boolean",
                    "description": "true if the message holds two or more separate things to deal with (not one request with a list of items, never a question).",
                },
                "chat_part": {
                    "type": "string",
                    "description": (
                        "With tasks only: the part of the message that is for no task (a general question "
                        "beside the request), copied word for word. Empty if there is none."
                    ),
                },
            },
            "required": ["kind", "tasks", "confidence", "reports_doing", "several", "chat_part"],
            "additionalProperties": False,
        },
    }


ABOUT_DATA = (
    "This message is about the user's own data, asks the bot to do something with it, or reports "
    "something the user did or took: plain chat said so, and chat has no access to that data and can "
    "record nothing. Choose the task that owns it. Answer chat or nothing only if no task here could "
    "possibly own it."
)


PART_OF_A_NAME = 4  # the fewest letters of a typed word that may be the start of a word of a name
WHOLE_WORD = 3  # a typed word this short is a hint only when it is a whole word of a name ("gym", an event called Gym)


def name_hints(message: str, named: dict[str, list[str]]) -> list[tuple[str, str]]:
    """(the word typed, the task) for each word of the message that is the
    start of a word in the name of something a task holds ("testv", with a
    pill called Testvit), or that word with an ending of a letter or two
    ("stretches", with a routine step called Stretch): four letters or more,
    whatever the case; or, from three letters, a whole word of a name of one or two words ("gym",
    with an event called Gym; never "the" in "Renew the passport").
    `named` is
    each task's names. Only a hint for the router, which still decides: a
    word such as "evening" may be part of a pill's name and mean nothing of
    the kind. Pure."""
    found: list[tuple[str, str]] = []
    for word in dict.fromkeys(names.words(message)):
        if len(word) < WHOLE_WORD:
            continue
        for task, held in named.items():
            if any(
                (len(word) >= PART_OF_A_NAME and of.startswith(word)) or (word == of and len(names.words(name)) <= 2)
                or (len(of) >= PART_OF_A_NAME and word.startswith(of) and len(word) - len(of) <= 2)
                for name in held for of in names.words(name)
            ):
                found.append((word, task))
    return found


def hint_line(hints: list[tuple[str, str]]) -> str:
    """The hints as the router is given them. No name of the user's is in it:
    only the word they typed and whose it might be."""
    said = "; ".join(f"“{word}” could be part of the name of one of the user's own things in {task}" for word, task in hints)
    return (
        f"A hint, not a decision: {said}. Weigh it with the rest of the message; the word may mean something else. "
        "If the message says such a thing was done (\"bought the milk\", with a to-do to buy milk), it is a report "
        "for that task (reports_doing true), never a remark."
    )


def user_turn(
    message: str,
    on_screen: str = "",
    exchanges: list[tuple[str, str]] | None = None,
    about_data: bool = False,
    attached: tuple[str, ...] = (),
    hints: list[tuple[str, str]] | tuple = (),
) -> str:
    """What changes from message to message: the last exchanges, what is on
    screen, and the message. Never part of the cached block. `about_data` is
    the second look, after chat said the message is about the user's data."""
    parts = [ABOUT_DATA] if about_data else []
    if exchanges:
        lines = ["The last exchanges, oldest first:"]
        for said, answered in exchanges[-EXCHANGES:]:
            lines += [f"User: {said}", f"Bot: {answered}"]
        parts.append("\n".join(lines))
    if on_screen:
        parts.append(f"On screen, waiting for the user: {on_screen}")
    if attached:
        # Only the names: what is in a file is for the task that takes it
        parts.append("Sent with the message, as a file: " + ", ".join(attached))
    if hints:
        parts.append(hint_line(list(hints)))
    parts.append(f"The message to route:\n{message}")
    return "\n\n".join(parts)


def parse(raw, names: list[str]) -> Route:
    """A Route from what the router's tool call held, checked in code. Anything
    that doesn't make sense is chat: the cheapest harmless reading."""
    if not isinstance(raw, dict):
        return Route(problem="the router returned no tool call")
    listed = raw.get("tasks")
    if not isinstance(listed, list):
        return Route(problem="`tasks` is not a list")
    tasks = tuple(dict.fromkeys(name for name in listed if isinstance(name, str) and name in names))
    unknown = [name for name in listed if name not in names]
    problem = f"unknown task(s): {unknown}" if unknown else ""
    reports = raw.get("reports_doing") is True
    if raw.get("kind") == NOTHING and not tasks:
        return Route(problem=problem, nothing=True, reports=reports)
    # Nothing with a task named is a task: something was asked for
    if raw.get("kind") == CHAT or not tasks:
        return Route(problem=problem, reports=reports)
    aside = raw.get("chat_part")
    return Route(
        tasks,
        tie=raw.get("confidence") == TIE and len(tasks) > 1,
        problem=problem,
        chat_part=aside.strip() if isinstance(aside, str) else "",
        reports=reports,
        several=raw.get("several") is True,
    )


_TO = r"(?:to|on|onto|in|into|from|off|for)"


def named_destinations(message: str, entries: list[Entry]) -> list[Entry]:
    """The tasks a message names as where something goes: "to my pills", "on
    the shopping list", "from the packing list". A stated destination decides
    the task outright, so this is read in code, not left to the router. Pure."""
    said = " ".join(message.lower().split())
    found = []
    for entry in entries:
        # Its name and the name it is shown by ("to-dos" for todos)
        names = {entry.name, entry.name.removesuffix("s"), entry.title.lower(), entry.title.lower().removesuffix("s")}
        name = "|".join(re.escape(each) for each in sorted(names, key=len, reverse=True))
        where = re.search(rf"\b{_TO} (?:my|the|our) (?:{name})(?: list| task)?\b", said)
        if where:
            found.append((where.start(), entry))
    # Two named in one clause ("add write in my diary to my to-dos"): the last is where it goes, the
    # first is part of what is added. Parts joined by "and" or a comma keep a destination each
    if len(found) > 1:
        found.sort(key=lambda each: each[0])
        kept = [found[-1]]
        for at, entry in reversed(found[:-1]):
            between = said[at:kept[0][0]]
            if re.search(r"\band\b|,|;", between):
                kept.insert(0, (at, entry))
        found = kept
    chosen = [entry for _, entry in found]
    return [entry for entry in entries if entry in chosen]


def led_by(message: str, entries: list[Entry]) -> Entry | None:
    """The task a message starts by asking for in so many words (`Entry.leads`: "remind me ..." is the
    reminders'), whatever else it names; None for none, or when two tasks could be meant. Pure."""
    said = " ".join(message.lower().split())
    found = [entry for entry in entries if any(re.match(rf"(?:please )?{re.escape(lead)}\b", said) for lead in entry.leads)]
    return found[0] if len(found) == 1 else None


def stated(message: str, entries: list[Entry]) -> list[str]:
    """The tasks the message settles in so many words: the destinations it names (`named_destinations`),
    unless it starts by asking a task in so many words (`led_by`): then that task, over the destination
    ("remind me to write in my diary" is a reminder). With no destination named, a lead settles nothing: the
    router reads it ("remind me to take my zinc at 8pm" is a pill's time, the pills', so no reminder names a
    pill on the lock screen). Pure."""
    named = [entry.name for entry in named_destinations(message, entries)]
    led = led_by(message, entries) if named else None
    return [led.name] if led is not None else named


def named_alone(message: str, entries: list[Entry]) -> Entry | None:
    """The task whose name is all the message says, with or without a plain
    way of asking to see it: "pills", "my pills", "shopping list", "show my
    timers", "show all my pills", "list my pills", "what are my pills". That
    asks to see what the task has, and is answered by code with no request.
    None for anything more than that ("what are pills?" is a question), and
    when two tasks could be meant. Pure."""
    said = re.sub(r"[\s.!?]+", " ", message.lower()).strip()
    found = []
    for entry in entries:
        names = {entry.name, entry.name.removesuffix("s"), entry.name + "s"}
        name = "|".join(re.escape(each) for each in sorted(names, key=len, reverse=True))
        shown = rf"(?:(?:show|list|see|open)(?: me)?(?: all(?: of)?)? )?(?:my |the |our )?(?:{name})(?: list)?"
        asked = rf"what(?: are| is|'s|s) (?:all )?(?:my|our) (?:{name})(?: list)?"
        if re.fullmatch(rf"(?:please )?(?:{shown}|{asked})(?: please)?", said):
            found.append(entry)
    return found[0] if len(found) == 1 else None


MIN_ITEM_NAME = 3  # shorter names ("a", "D") are too easily a word of something else


def names_item(message: str, names: list[str]) -> str | None:
    """The first of `names` that the message says, whole and whatever the case
    ("I've taken my Zinc today" names Zinc). A check on the router, not a way
    of understanding the message: it only says whose the message is. Pure."""
    said = " ".join(message.lower().split())
    for name in names:
        wanted = " ".join(name.lower().split())
        if len(wanted) >= MIN_ITEM_NAME and re.search(rf"(?<!\w){re.escape(wanted)}(?!\w)", said):
            return name
    return None


def with_named(found: Route, named: list[str]) -> Route:
    """The router's answer once the destinations the user named are taken as
    settled. If the router agrees and adds other tasks (a message with several
    parts), they stay; if it chose something else, the named task stands
    alone. Never a tie, and never chat. Pure."""
    if not named:
        return found
    if all(name in found.tasks for name in named):
        return Route(found.tasks, tie=False, problem=found.problem, chat_part=found.chat_part, reports=found.reports, several=found.several)
    return Route(tuple(named), problem=found.problem, reports=found.reports)


async def route(
    message: str, entries: list[Entry], on_screen: str = "", exchanges=None, about_data: bool = False, attached: tuple[str, ...] = (),
    hints: list[tuple[str, str]] | tuple = (),
) -> Route:
    """Ask the router. One request; the result is checked and never raises for
    something the router got wrong. `hints` are words of the message that may
    be part of the name of something a task holds (`name_hints`)."""
    called = await llm.call_tool(
        system_blocks(entries),
        user_turn(message, on_screen, exchanges, about_data, attached, hints),
        [tool(entries)],
        choice={"type": "tool", "name": TOOL},
        purpose=costs.PURPOSE_ROUTER,
        max_tokens=MAX_TOKENS,
    )
    found = parse(called[1] if called else None, [entry.name for entry in entries])
    if found.problem:
        log.warning("Router: %s (it returned %s)", found.problem, called)
    return found
