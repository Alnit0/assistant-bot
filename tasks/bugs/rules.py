import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from core.config import CHANNELS, TIMEZONE
from core.database import OWN_MESSAGE_KINDS
from core.errors import UserError

# ---------------------------------------------------------------------------
# Bug reports: what may be reported, which logged turn a message belongs to,
# which log lines go with it, and every piece of wording (the forum post, the
# list, docs/BUGS.md). No Discord and no database in here: plain values in,
# plain values out.
# ---------------------------------------------------------------------------
BUG_EMOJI = "🐞"

OPEN, FIXED, WONTFIX = "open", "fixed", "wontfix"
# The forum's tags, by status
TAGS = {OPEN: "Open", FIXED: "Fixed", WONTFIX: "Won't fix"}

# How a report was made
REACTION, REPLY, WORD = "reaction", "reply", "word"
SOURCES = {REACTION: f"a {BUG_EMOJI} reaction", REPLY: "a reply", WORD: "the word"}

# Who wrote a note: the owner in the post, or Claude Code after a fix
OWNER, CLAUDE_CODE = "owner", "claude-code"
FIX_READY = "fix ready, needs retest"

PRECEDING = 5  # messages before the target that are captured with it
TITLE_LIMIT = 100  # Discord's limit for a post's title
SUMMARY_LENGTH = 60
CLIP = 300  # how much of one message or result the post shows
ERROR_CHARS = 1500  # how much of the log the post shows (all of it is kept)
ERROR_LINES = 60  # how many log lines are kept with a report
TURN_SLACK = timedelta(seconds=5)  # our clock and Discord's are not the same clock
LOG_BEFORE, LOG_AFTER = timedelta(seconds=5), timedelta(seconds=30)

IN_POST = "That is already in a bug's post: write the note there instead."
QUESTIONS = (
    "**To help fix it, reply here with:**\n"
    "1. What did you expect?\n"
    "2. What happened instead?\n"
    "3. Has it happened before?\n"
    "-# Anything you write in this post is saved as a note (✅). "
    "Press Fixed or Won't fix when it is settled."
)


# --- ids ---------------------------------------------------------------------
def bug_id(number: int) -> str:
    return f"B{number}"


def parse_id(text: str) -> int:
    """The number in "B4" (or "b4", or "4"). Raises UserError for anything else."""
    found = re.fullmatch(r"[bB]?(\d+)", text.strip())
    if found is None:
        raise UserError(f"“{text}” isn't a bug id. They look like B4.")
    return int(found.group(1))


# --- where -------------------------------------------------------------------
def in_bugs_forum(parent_channel_id: int | None) -> bool:
    """True for a post in the #bugs forum (a thread whose parent is that channel)."""
    return parent_channel_id is not None and parent_channel_id == CHANNELS.get("bugs")


def check_reportable(message) -> None:
    """Raise UserError if this message can't be reported: it is inside a bug's post."""
    if in_bugs_forum(getattr(message.channel, "parent_id", None)):
        raise UserError(IN_POST)


def channel_label(channel_id: int) -> str:
    """Our name for a channel ("#inbox"), or a mention Discord will show as its name."""
    for name, known_id in CHANNELS.items():
        if known_id == channel_id:
            return f"#{name}"
    return f"<#{channel_id}>"


# --- what is captured --------------------------------------------------------
@dataclass(frozen=True)
class Snapshot:
    """One message as it was when the bug was reported."""

    message_id: int
    author: str
    content: str
    at: str  # UTC, ISO
    url: str = ""


@dataclass
class Report:
    source: str  # REACTION, REPLY or WORD
    channel_id: int
    channel: str  # as channel_label gives it
    target: Snapshot
    preceding: list[Snapshot] = field(default_factory=list)  # oldest first
    turn: dict | None = None  # see pick_turn
    errors: list[str] = field(default_factory=list)  # lines from bot.log
    commit: str = "unknown"
    reported_at: str = ""  # UTC, ISO

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "Report":
        value = json.loads(text)
        value["target"] = Snapshot(**value["target"])
        value["preceding"] = [Snapshot(**item) for item in value["preceding"]]
        return cls(**value)


def message_text(message) -> str:
    """What a message says, including a card's title and text and a count of files."""
    parts = [(getattr(message, "content", "") or "").strip()]
    for embed in getattr(message, "embeds", None) or []:
        card = " · ".join(
            part for part in (getattr(embed, "title", None), getattr(embed, "description", None)) if part
        )
        if card:
            parts.append(f"[card] {card}")
    files = len(getattr(message, "attachments", None) or [])
    if files:
        parts.append(f"[{files} attachment{'' if files == 1 else 's'}]")
    return "\n".join(part for part in parts if part) or "(no text)"


def snapshot(message) -> Snapshot:
    """A message of Discord's as plain values."""
    author = getattr(message.author, "display_name", None) or str(message.author)
    return Snapshot(
        message.id, author, message_text(message), message.created_at.isoformat(), getattr(message, "jump_url", "") or ""
    )


# --- which turn a message belongs to ----------------------------------------
def pick_turn(rows: list[dict], target_message_id: int, target_at: datetime, exclude_message_id: int | None = None):
    """The logged turn a reported message belongs to, or None.

    `rows` are the channel's latest message_log rows, newest first. A message
    of the user's is found by its id. A message of the bot's has no row of its
    own, so it belongs to the latest thing the user sent before it. The tool
    calls of that turn are logged against the same message. `exclude_message_id`
    is the "bug" command itself.
    """
    rows = [row for row in rows if exclude_message_id is None or row["discord_message_id"] != exclude_message_id]
    own = [row for row in rows if row["kind"] in OWN_MESSAGE_KINDS]
    lead = next((row for row in own if row["discord_message_id"] == target_message_id), None)
    if lead is None:
        latest = target_at + TURN_SLACK
        lead = next((row for row in own if datetime.fromisoformat(row["received_at"]) <= latest), None)
    if lead is None:
        return None
    calls = [
        row
        for row in rows
        if row["kind"] == "tool"
        and lead["discord_message_id"] is not None
        and row["discord_message_id"] == lead["discord_message_id"]
    ]
    return {
        "received_at": lead["received_at"],
        "kind": lead["kind"],
        "input": lead["content"],
        "reply": lead["reply"],
        "status": lead["status"],
        "error": lead["error"],
        "duration_s": lead["duration_s"],
        "timing": json.loads(lead["timing"]) if lead.get("timing") else None,
        "tools": [
            {
                "call": row["content"].removeprefix("tool: "),
                "result": row["reply"],
                "status": row["status"],
                "error": row["error"],
            }
            for row in sorted(calls, key=lambda row: row["id"])
        ],
    }


# --- which log lines go with it ---------------------------------------------
def log_window(turn: dict | None, target_at: datetime) -> tuple[datetime, datetime]:
    """The stretch of bot.log worth reading for a report: the turn, with a little
    either side; or a minute either side of the message if no turn was found."""
    if turn is None:
        return target_at - timedelta(seconds=60), target_at + timedelta(seconds=60)
    started = datetime.fromisoformat(turn["received_at"])
    return started - LOG_BEFORE, started + timedelta(seconds=turn["duration_s"] or 60) + LOG_AFTER


_LOG_RECORD = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d{3} (\w+) ")
_LOG_LEVELS = ("WARNING", "ERROR", "CRITICAL")


def related_errors(lines: list[str], start: datetime, end: datetime, limit: int = ERROR_LINES) -> list[str]:
    """The warnings and errors logged from `start` to `end`, with their tracebacks.

    `lines` are bot.log's; `start` and `end` are in the log's own clock (the
    machine's local time, with no zone). A line that doesn't begin a record
    belongs to the record before it.
    """
    found: list[str] = []
    keeping = False
    for line in lines:
        line = line.rstrip("\n")
        record = _LOG_RECORD.match(line)
        if record is not None:
            when = datetime.strptime(record.group(1), "%Y-%m-%d %H:%M:%S")
            keeping = record.group(2) in _LOG_LEVELS and start.replace(microsecond=0) <= when <= end
        if keeping and line.strip():
            found.append(line)
    if len(found) > limit:
        found = found[:limit] + [f"… and {len(found) - limit} more lines"]
    return found


# --- wording -----------------------------------------------------------------
def clip(text: str | None, limit: int = CLIP) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summary(content: str, limit: int = SUMMARY_LENGTH) -> str:
    """The start of a message on one line, for a title or a list."""
    return clip(" ".join(content.split()), limit) or "(no text)"


def title(number: int, content: str) -> str:
    """A post's title: "B4 · the start of the message"."""
    return f"{bug_id(number)} · {summary(content)}"[:TITLE_LIMIT]


def logged_text(number: int, url: str | None, existing: bool = False) -> str:
    """The line left in the channel the bug was reported from."""
    name = f"[{bug_id(number)}]({url})" if url else bug_id(number)
    return f"{BUG_EMOJI} {'Already logged' if existing else 'Logged'} as {name}"


def closed_text(number: int, status: str, already: bool = False) -> str:
    return f"{'Already' if already else '✅'} {bug_id(number)} {'is ' if already else ''}closed as {TAGS[status]}"


def _local(at: str) -> datetime:
    return datetime.fromisoformat(at).astimezone(TIMEZONE)


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines() or [""])


def _turn_lines(turn: dict | None, brief: bool) -> list[str]:
    if turn is None:
        return ["No logged turn was found for this message."]
    cut = (lambda text: clip(text)) if brief else (lambda text: (text or "").strip())
    took = f" in {turn['duration_s']:.1f}s" if turn["duration_s"] else ""
    lines = [f"Input ({turn['kind']}): `{cut(turn['input'])}`", f"Outcome: {turn['status']}{took}"]
    if turn["error"]:
        lines.append(f"Error: {cut(turn['error'])}")
    if turn["reply"]:
        lines.append(f"Reply: {cut(turn['reply'])}")
    for call in turn["tools"]:
        outcome = call["error"] or call["result"] or ""
        lines.append(f"🔧 `{cut(call['call'])}` ({call['status']}) {cut(outcome)}".rstrip())
    timing = turn["timing"]
    if timing:
        # Read with defaults: a row may have been written by an older version
        claude = " + ".join(f"{call['seconds']:.2f}s" for call in timing.get("claude", [])) or "none"
        tools = ", ".join(
            f"{run['name']} {run['seconds']:.2f}s{' (failed)' if run.get('failed') else ''}"
            for run in timing.get("tools", [])
        ) or "none"
        lines.append(
            f"Timings: {timing.get('total_s', 0):.2f}s to the reply · Claude {claude} · tools {tools} · "
            f"Discord {timing.get('discord_s', 0):.2f}s over {timing.get('discord_calls', 0)} calls · "
            f"{timing.get('rate_limits', 0)} rate-limit waits · {timing.get('claude_retries', 0)} Claude retries"
        )
    return lines


def _error_block(errors: list[str], brief: bool) -> str:
    if not errors:
        return "None in the log around that time."
    text = "\n".join(errors).replace("```", "'''")
    if brief and len(text) > ERROR_CHARS:
        text = text[:ERROR_CHARS] + "\n… (the rest is in `bugs export`)"
    return f"```\n{text}\n```"


def sections(report: Report, brief: bool = False) -> list[tuple[str, str]]:
    """Everything captured with a report, as (heading, text). `brief` shortens
    long messages and the log to what fits in a Discord message."""
    cut = (lambda text: clip(text)) if brief else (lambda text: text)
    target = report.target
    link = f" · [jump]({target.url})" if target.url else ""
    message = f"{target.author}, {_local(target.at):%H:%M}{link}\n{_quote(cut(target.content))}"
    before = "\n".join(
        f"`{_local(item.at):%H:%M}` **{item.author}**: {cut(item.content)}" for item in report.preceding
    )
    return [
        ("Message", message),
        ("Before it", before or "Nothing before it in the channel."),
        ("That turn", "\n".join(_turn_lines(report.turn, brief))),
        ("Related errors", _error_block(report.errors, brief)),
    ]


def post_sections(number: int, report: Report) -> list[str]:
    """The forum post, a message at a time: the first opens the post, the last
    is the questions."""
    when = int(datetime.fromisoformat(report.reported_at).timestamp())
    header = (
        f"{BUG_EMOJI} **{bug_id(number)}** · from {report.channel} · <t:{when}:f> · "
        f"by {SOURCES[report.source]} · commit `{report.commit}`"
    )
    (first_heading, first), *rest = sections(report, brief=True)
    return (
        [f"{header}\n\n**{first_heading}**\n{first}"]
        + [f"**{heading}**\n{text}" for heading, text in rest]
        + [QUESTIONS]
    )


def missing_tags(existing: list[str]) -> list[str]:
    """The tags the forum still needs, given the names it has."""
    have = {name.lower() for name in existing}
    return [name for name in TAGS.values() if name.lower() not in have]


def tags_after(current: list[str], status: str) -> list[str]:
    """A post's tag names once it has this status: ours replaced, any others kept."""
    ours = {name.lower() for name in TAGS.values()}
    return [name for name in current if name.lower() not in ours] + [TAGS[status]]


def list_text(items: list) -> str:
    """What `bugs` shows: one line per open bug, oldest first."""
    if not items:
        return f"{BUG_EMOJI} No open bugs."
    lines = [f"**Open bugs ({len(items)})**"]
    for item in items:
        name = f"[{bug_id(item.id)}]({item.post_url})" if item.post_url else bug_id(item.id)
        line = f"• {name} · {item.summary} · {item.report.channel} · {_local(item.created_at):%d %b}"
        if item.note_count:
            line += f" · {item.note_count} note{'' if item.note_count == 1 else 's'}"
        if item.fix_ready:
            line += f" · 🔧 {FIX_READY}"
        lines.append(line)
    return "\n".join(lines)


def detail_text(item, notes: list) -> str:
    """One bug in full, as Markdown: for docs/BUGS.md and for Claude Code."""
    report = item.report
    lines = [
        f"## {bug_id(item.id)} · {item.summary}",
        "",
        f"- Status: {TAGS[item.status]}",
        f"- Reported: {_local(item.created_at):%Y-%m-%d %H:%M} (NZ) from {report.channel} by {SOURCES[report.source]}",
        f"- Commit: `{report.commit}`",
    ]
    if item.post_url:
        lines.append(f"- Post: {item.post_url}")
    for heading, text in sections(report):
        lines += ["", f"### {heading}", "", text]
    lines += ["", "### Notes", ""]
    lines += [
        f"- {_local(note.created_at):%Y-%m-%d %H:%M} ({note.author}): {note.content}" for note in notes
    ] or ["None yet."]
    return "\n".join(lines)


def export_text(entries: list[tuple], now: datetime) -> str:
    """docs/BUGS.md: every open bug with all that was captured and its notes."""
    count = len(entries)
    head = [
        "# Open bugs",
        "",
        f"Written by `bugs export` on {now.astimezone(TIMEZONE):%Y-%m-%d %H:%M} (NZ): "
        f"{count} open bug{'' if count == 1 else 's'}. Not in git: it holds Discord messages.",
    ]
    return "\n".join(head) + "".join(f"\n\n{detail_text(item, notes)}" for item, notes in entries) + "\n"
