import logging
from dataclasses import dataclass

from core import actions, costs, llm
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
TASK, CHAT = "task", "chat"
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
    "- A message can hold both: a request for a task and, beside it, a general question or remark that "
    "is for no task (\"what's the capital of France, and add milk to the shopping list\"). Then give "
    "the task as usual and copy the part that is for no task into chat_part, word for word. Every part "
    "of a message must be dealt with. Leave chat_part empty when the whole message is for the task(s); "
    "a greeting or a please is not a part.\n"
    "- A reply to what is on screen usually belongs to the same task as that."
)


@dataclass(frozen=True)
class Route:
    tasks: tuple[str, ...] = ()  # the tasks to hand the message to, likeliest first
    tie: bool = False  # the user must say which of `tasks` they mean
    problem: str = ""  # what was wrong with what the router returned, if anything
    # With tasks: the part of the message that is for none of them (a general
    # question beside the request), to be answered as chat as well
    chat_part: str = ""

    @property
    def chat(self) -> bool:
        return not self.tasks


def catalogue_text(entries: list[Entry]) -> str:
    """The tasks as the router reads them. Fixed text for a given set of tasks."""
    lines = ["The tasks:"]
    for entry in entries:
        examples = "; ".join(f"\"{example}\"" for example in entry.examples)
        lines.append(f"- {entry.name}: {entry.only_for} For example: {examples}")
    return "\n".join(lines)


def system_blocks(entries: list[Entry]) -> list[dict]:
    """The router's instructions and the catalogue: one block, the same for every
    message, marked for caching."""
    return [{"type": "text", "text": f"{RULES}\n\n{catalogue_text(entries)}", "cache_control": llm.CACHED}]


def tool(entries: list[Entry]) -> dict:
    return {
        "name": TOOL,
        "description": "Say which task or tasks the message is for, or that it is for none.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": [TASK, CHAT], "description": "chat if it is for no task."},
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
                "chat_part": {
                    "type": "string",
                    "description": (
                        "With tasks only: the part of the message that is for no task (a general question "
                        "beside the request), copied word for word. Empty if there is none."
                    ),
                },
            },
            "required": ["kind", "tasks", "confidence", "chat_part"],
            "additionalProperties": False,
        },
    }


def user_turn(message: str, on_screen: str = "", exchanges: list[tuple[str, str]] | None = None) -> str:
    """What changes from message to message: the last exchanges, what is on
    screen, and the message. Never part of the cached block."""
    parts = []
    if exchanges:
        lines = ["The last exchanges, oldest first:"]
        for said, answered in exchanges[-EXCHANGES:]:
            lines += [f"User: {said}", f"Bot: {answered}"]
        parts.append("\n".join(lines))
    if on_screen:
        parts.append(f"On screen, waiting for the user: {on_screen}")
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
    if raw.get("kind") == CHAT or not tasks:
        return Route(problem=problem)
    aside = raw.get("chat_part")
    return Route(
        tasks,
        tie=raw.get("confidence") == TIE and len(tasks) > 1,
        problem=problem,
        chat_part=aside.strip() if isinstance(aside, str) else "",
    )


async def route(message: str, entries: list[Entry], on_screen: str = "", exchanges=None) -> Route:
    """Ask the router. One request; the result is checked and never raises for
    something the router got wrong."""
    called = await llm.call_tool(
        system_blocks(entries),
        user_turn(message, on_screen, exchanges),
        [tool(entries)],
        choice={"type": "tool", "name": TOOL},
        purpose=costs.PURPOSE_ROUTER,
        max_tokens=MAX_TOKENS,
    )
    found = parse(called[1] if called else None, [entry.name for entry in entries])
    if found.problem:
        log.warning("Router: %s (it returned %s)", found.problem, called)
    return found
