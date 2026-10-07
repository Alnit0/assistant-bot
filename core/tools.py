import re
from dataclasses import dataclass, field
from datetime import datetime

# ---------------------------------------------------------------------------
# Tools for Claude: the decisions, with no Discord and no API calls.
#
# Every registered word and reply action becomes one tool, generated from what
# the registration says about itself (skills/registry.py does the gathering).
# This file names them, builds their input schemas, checks what Claude sends
# against those schemas, and decides which message a reply action is aimed at.
# ---------------------------------------------------------------------------
STRICT_LIMIT = 20  # the API accepts at most this many `strict` tools in one request
MAX_CANDIDATES = 5  # more possible targets than this is a question, not a set of buttons
LISTING_LIMIT = 20  # how many recent messages Claude may choose a target from
PREVIEW_LENGTH = 80

KEYWORD, REPLY_ACTION, HELPER = "keyword", "reply_action", "helper"

PROPOSE = "propose"
TARGETS = "targets"

PROPOSE_DESCRIPTION = (
    "false when the user has clearly asked for this. true only when you are suggesting it "
    "yourself: nothing is done until the user replies ok."
)
TARGETS_DESCRIPTION = (
    "Which message to act on. Leave empty if the user's message is a reply: the message they "
    "replied to is used. Otherwise call recent_messages first and give the ref (such as m3) of "
    "the message they mean. If more than one could be meant, give each of them and the user "
    "is asked to pick."
)


@dataclass(frozen=True)
class ToolSpec:
    """One tool as Claude sees it, and what it stands for."""

    name: str  # as sent to the API
    description: str
    schema: dict
    kind: str  # KEYWORD, REPLY_ACTION or HELPER
    skill: str = ""
    item: object = None  # the Keyword or ReplyAction it runs
    has_arguments: bool = False  # takes something beyond `propose` and `targets`
    priority: int = 0  # higher gets `strict` first
    destructive: bool = False


def tool_name(kind: str, name: str) -> str:
    """The API name for a registration: "pomo stats" -> pomo_stats, a reply "archive" -> reply_archive."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (f"reply_{slug}" if kind == REPLY_ACTION else slug)[:64]


# ---------------------------------------------------------------------------
# Schemas. Every property is required and none is a union: an argument that
# may be left out is a string that may be empty. That keeps clear of the API's
# limits on optional and union-typed parameters across strict tools.
# ---------------------------------------------------------------------------
def build_schema(params=(), *, propose: bool = False, targets: bool = False) -> dict:
    properties: dict[str, dict] = {}
    for param in params:
        description = param.description
        if not param.required:
            description += " Use an empty string to leave it out."
        entry: dict = {"type": "string", "description": description}
        if param.choices:
            entry["enum"] = [*param.choices] + ([] if param.required else [""])
        properties[param.name] = entry
    if targets:
        properties[TARGETS] = {"type": "array", "items": {"type": "string"}, "description": TARGETS_DESCRIPTION}
    if propose:
        properties[PROPOSE] = {"type": "boolean", "description": PROPOSE_DESCRIPTION}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_TYPES = {"string": str, "boolean": bool, "array": list}


def validate(schema: dict, value) -> list[str]:
    """What is wrong with a tool input, in words. Empty if it fits the schema.

    Run on every call, whether or not the tool was sent as `strict`.
    """
    if not isinstance(value, dict):
        return ["the input must be an object"]
    properties = schema["properties"]
    problems = [f"`{name}` is missing" for name in schema["required"] if name not in value]
    problems += [f"`{name}` is not an argument of this tool" for name in value if name not in properties]
    for name, rules in properties.items():
        if name not in value:
            continue
        given = value[name]
        if not isinstance(given, _TYPES[rules["type"]]):
            problems.append(f"`{name}` must be a {rules['type']}")
        elif rules["type"] == "array" and not all(isinstance(entry, str) for entry in given):
            problems.append(f"`{name}` must be a list of strings")
        elif "enum" in rules and given not in rules["enum"]:
            choices = ", ".join(repr(choice) for choice in rules["enum"])
            problems.append(f"`{name}` must be one of {choices}")
    return problems


def to_args(params, value: dict) -> list[str]:
    """A tool input as the words a typed command would have had, in the order the
    registration lists its arguments. Empty values are left out."""
    words: list[str] = []
    for param in params:
        words += str(value.get(param.name, "")).split()
    return words


def command_text(name: str, args: list[str]) -> str:
    """The call as if it had been typed: "timer 5m tea"."""
    return " ".join([name, *args])


# ---------------------------------------------------------------------------
# Which tools are sent as strict
# ---------------------------------------------------------------------------
def choose_strict(specs: list[ToolSpec], limit: int = STRICT_LIMIT) -> tuple[set[str], list[str]]:
    """The tools to send with `strict: true`, and the ones that had to go without.

    Only tools with real arguments need it (the rest have nothing to get
    wrong). If there are more than the API allows, the likeliest to be used
    come first; the overflow is still checked by validate().
    """
    with_arguments = [spec for spec in specs if spec.has_arguments]
    ranked = sorted(with_arguments, key=lambda spec: -spec.priority)  # stable: registration order within a priority
    return {spec.name for spec in ranked[:limit]}, [spec.name for spec in ranked[limit:]]


def api_definition(spec: ToolSpec, strict: bool) -> dict:
    definition = {"name": spec.name, "description": spec.description, "input_schema": spec.schema}
    if strict:
        definition["strict"] = True
    return definition


# ---------------------------------------------------------------------------
# Which message a reply action is aimed at
# ---------------------------------------------------------------------------
REPLY, ONE, MANY, ERROR = "reply", "one", "many", "error"


@dataclass(frozen=True)
class Resolution:
    kind: str  # REPLY, ONE, MANY or ERROR
    refs: list[str] = field(default_factory=list)
    error: str = ""


def resolve_targets(is_reply: bool, refs: list[str], listed: set[str]) -> Resolution:
    """Decide what a message action acts on.

    A reply always wins: whatever Claude named, it is the message the user
    replied to. Otherwise the refs must come from the recent_messages listing
    of this turn: one acts, a few are offered as buttons, and none, an unknown
    one or too many is an error for Claude to put right.
    """
    if is_reply:
        return Resolution(REPLY)
    wanted = list(dict.fromkeys(ref.strip().lower() for ref in refs if ref.strip()))
    if not wanted:
        return Resolution(
            ERROR,
            error="No message was named and the user did not reply to one. Call recent_messages, "
            "then pass the ref of the message they mean, or ask them which message.",
        )
    unknown = [ref for ref in wanted if ref not in listed]
    if unknown:
        return Resolution(
            ERROR,
            error=f"Unknown message ref: {', '.join(unknown)}. Use refs from recent_messages in this turn "
            f"(only the last {LISTING_LIMIT} messages of this channel can be acted on).",
        )
    if len(wanted) > MAX_CANDIDATES:
        return Resolution(
            ERROR,
            error=f"{len(wanted)} messages could be meant, which is too many to offer. Ask the user "
            "which one they mean, or to reply to it.",
        )
    return Resolution(ONE if len(wanted) == 1 else MANY, wanted)


# ---------------------------------------------------------------------------
# Words: previews, confirmations and the listing Claude chooses from
# ---------------------------------------------------------------------------
def preview(content: str | None, limit: int = PREVIEW_LENGTH) -> str:
    """The start of a message on one line, for quoting."""
    text = " ".join((content or "").split())
    if not text:
        return "(no text)"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def confirmation_text(outcome: str, quoted: str, link: str | None = None) -> str:
    """What is shown after acting on a message the user didn't reply to: what was
    done, the message quoted, and a link to it unless the outcome already has one."""
    lines = [outcome, f"> {quoted}"]
    if link and "https://" not in outcome:
        lines.append(f"-# {link}")
    return "\n".join(lines)


def question_text(what: str, quoted: str | None = None, link: str | None = None) -> str:
    """The Confirm / Cancel question before a destructive action."""
    lines = [f"⚠️ {what} Go ahead?"]
    if quoted is not None:
        lines.append(f"> {quoted}")
    if link:
        lines.append(f"-# {link}")
    return "\n".join(lines)


def age(created_at: datetime, now: datetime) -> str:
    seconds = max(0, int((now - created_at).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


@dataclass(frozen=True)
class Listed:
    """One recent message, as Claude is shown it."""

    ref: str
    author: str
    created_at: datetime
    content: str | None
    tags: tuple[str, ...] = ()


def listing_text(entries: list[Listed], now: datetime) -> str:
    """The recent messages of a channel, newest first, one per line."""
    if not entries:
        return "There are no recent messages in this channel to act on."
    lines = ["Recent messages in this channel, newest first. Use the ref to act on one:"]
    for entry in entries:
        tags = f" [{', '.join(entry.tags)}]" if entry.tags else ""
        lines.append(f"{entry.ref}: {entry.author}, {age(entry.created_at, now)}{tags}: {preview(entry.content)}")
    return "\n".join(lines)
