import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from core.config import CHANNELS, DEV_DATABASE, TIMEZONE
from core.database import OWN_MESSAGE_KINDS
from core.errors import UserError
from core.timeinput import format_time

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
STATUS_MARKS = {OPEN: "🟢", FIXED: "✅", WONTFIX: "🚫"}
# What happened to a bug after it was reported, as its history words it
REOPENED = "reopened"
EVENTS = {FIXED: "Closed as Fixed", WONTFIX: "Closed as Won't fix", REOPENED: "Re-opened"}
CARD_LIMIT = 2000  # Discord's limit for one message

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
TRACE_CHARS = 1700  # and of the turn's trace: a section is one Discord message
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
# A bug's number is its row's primary key, which SQLite never gives out twice
# (AUTOINCREMENT): it is never worked out from a count of rows or of posts. The
# letter in front says which database it is in: B for the live one, D for the
# dev database (`--dev`), whose numbers start again whenever it is recreated.
# Both post to the same forum, so a dev bug also carries the "dev" tag.
DEV = DEV_DATABASE  # which database this is; never the channel a bug came from
LIVE_PREFIX, DEV_PREFIX = "B", "D"
DEV_TAG = "dev"


def prefix() -> str:
    return DEV_PREFIX if DEV else LIVE_PREFIX


def bug_id(number: int) -> str:
    return f"{prefix()}{number}"


def parse_id(text: str) -> int:
    """The number in "B4" (or "b4", or "4"); "D4" on the dev database. Raises
    UserError for anything else, the other database's ids included."""
    letter = prefix()
    found = re.fullmatch(rf"[{letter.lower()}{letter}]?(\d+)", text.strip())
    if found is None:
        raise UserError(f"“{text}” isn't a bug id. They look like {letter}4.")
    return int(found.group(1))


def tags_for_new() -> list[str]:
    """The tags a new post gets: Open, and "dev" for a bug of the dev database."""
    return [TAGS[OPEN]] + ([DEV_TAG] if DEV else [])


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
    # What `dev why` would show for that turn (core/trace.py): the route and why,
    # what the router and extraction returned, what the code applied, the cost
    trace: list[str] = field(default_factory=list)

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
        "id": lead["id"],  # the message_log row: its trace goes with the report
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


def reopened_text(number: int, already: bool = False) -> str:
    return f"{bug_id(number)} is already open" if already else f"🔄 {bug_id(number)} re-opened"


def changed_text(number: int, status: str, already: bool = False) -> str:
    """What is said in the post when a button is pressed."""
    return reopened_text(number, already) if status == OPEN else closed_text(number, status, already)


def _local(at: str) -> datetime:
    return datetime.fromisoformat(at).astimezone(TIMEZONE)


def _time(at: str) -> str:
    """The time of day of a moment, in NZ time, as it is always shown: "2:00 pm"."""
    return format_time(_local(at).time())


def _stamp(at: str) -> str:
    """A date and time for the record: "2026-10-09 2:00 pm"."""
    return f"{_local(at):%Y-%m-%d} {_time(at)}"


def clock(at: str) -> str:
    """A moment as the card shows it, in NZ time: "1:25 pm, 9 Oct"."""
    local = _local(at)
    return f"{_time(at)}, {local.day} {local:%b}"


def notes_text(count: int) -> str:
    return "No notes yet" if count == 0 else f"{count} note{'' if count == 1 else 's'}"


def status_line(status: str, changed_at: str | None = None, note_count: int = 0) -> str:
    """The foot of a post's opening card: "✅ Fixed · 1:25pm, 9 Oct · 📝 2 notes".
    `changed_at` is when it was last closed or re-opened, if it ever was."""
    parts = [f"{STATUS_MARKS[status]} {TAGS[status]}"]
    if changed_at:
        parts.append(clock(changed_at))
    return "-# " + " · ".join(parts + [f"📝 {notes_text(note_count)}"])


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


def _trace_block(lines: list[str], brief: bool) -> str:
    text = "\n".join(lines).replace("```", "'''")
    if brief and len(text) > TRACE_CHARS:
        text = text[:TRACE_CHARS] + "\n… (the rest is in `bugs export`)"
    return f"```\n{text}\n```"


def sections(report: Report, brief: bool = False) -> list[tuple[str, str]]:
    """Everything captured with a report, as (heading, text). `brief` shortens
    long messages and the log to what fits in a Discord message."""
    cut = (lambda text: clip(text)) if brief else (lambda text: text)
    target = report.target
    link = f" · [jump]({target.url})" if target.url else ""
    message = f"{target.author}, {_time(target.at)}{link}\n{_quote(cut(target.content))}"
    before = "\n".join(
        f"`{_time(item.at)}` **{item.author}**: {cut(item.content)}" for item in report.preceding
    )
    found = [
        ("Message", message),
        ("Before it", before or "Nothing before it in the channel."),
        ("That turn", "\n".join(_turn_lines(report.turn, brief))),
    ]
    if report.trace:
        found.append(("Trace", _trace_block(report.trace, brief)))
    return found + [("Related errors", _error_block(report.errors, brief))]


def opening_text(
    number: int, report: Report, status: str = OPEN, changed_at: str | None = None, note_count: int = 0
) -> str:
    """The post's opening card: where the bug came from, the message, and a foot
    with its status and note count. Rewritten in place whenever either changes,
    so it is built from the record every time and always fits one message."""
    when = int(datetime.fromisoformat(report.reported_at).timestamp())
    header = (
        f"{BUG_EMOJI} **{bug_id(number)}** · from {report.channel} · <t:{when}:f> · "
        f"by {SOURCES[report.source]} · commit `{report.commit}`"
    )
    heading, message = sections(report, brief=True)[0]
    foot = "\n\n" + status_line(status, changed_at, note_count)
    return clip(f"{header}\n\n**{heading}**\n{message}", CARD_LIMIT - len(foot)) + foot


def post_sections(number: int, report: Report) -> list[str]:
    """The forum post, a message at a time: the first is the opening card, the
    last is the questions."""
    rest = sections(report, brief=True)[1:]
    return [opening_text(number, report)] + [f"**{heading}**\n{text}" for heading, text in rest] + [QUESTIONS]


def missing_tags(existing: list[str]) -> list[str]:
    """The tags the forum still needs, given the names it has. The "dev" tag is
    only asked for by a bot on the dev database."""
    have = {name.lower() for name in existing}
    wanted = [*TAGS.values(), *([DEV_TAG] if DEV else [])]
    return [name for name in wanted if name.lower() not in have]


def tags_problem(missing: list[str], forbidden: bool, detail: str = "") -> str:
    """The one warning for tags that couldn't be created: which, why, and what to do."""
    names = ", ".join(missing)
    if forbidden:
        return (
            f"The bot needs the **Manage Channels** permission in #bugs to create its tags ({names}). "
            "Grant it and restart the bot, or add those tags to the forum by hand. "
            "Until then bugs are still logged, without the tag."
        )
    return f"Discord refused the tags ({names}): {detail}. They are tried again at the next start."


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


def history_lines(created_at: str, events=()) -> list[str]:
    """A bug's history, oldest first: reported, then each closing and re-opening."""
    moments = [(created_at, "Reported")] + [(event.created_at, EVENTS[event.event]) for event in events]
    return [f"- {_stamp(at)}: {what}" for at, what in moments]


def detail_text(item, notes: list, events=()) -> str:
    """One bug in full, as Markdown: for docs/BUGS.md and for Claude Code."""
    report = item.report
    lines = [
        f"## {bug_id(item.id)} · {item.summary}",
        "",
        f"- Status: {TAGS[item.status]}",
        f"- Reported: {_stamp(item.created_at)} (NZ) from {report.channel} by {SOURCES[report.source]}",
        f"- Commit: `{report.commit}`",
    ]
    if item.post_url:
        lines.append(f"- Post: {item.post_url}")
    for heading, text in sections(report):
        lines += ["", f"### {heading}", "", text]
    lines += ["", "### Notes", ""]
    lines += [
        f"- {_stamp(note.created_at)} ({note.author}): {note.content}" for note in notes
    ] or ["None yet."]
    lines += ["", "### History", ""] + history_lines(item.created_at, events)
    return "\n".join(lines)


def export_text(entries: list[tuple], now: datetime) -> str:
    """docs/BUGS.md: every open bug with all that was captured and its notes."""
    count = len(entries)
    head = [
        "# Open bugs",
        "",
        f"Written by `bugs export` on {now.astimezone(TIMEZONE):%Y-%m-%d} {format_time(now.astimezone(TIMEZONE).time())} (NZ): "
        f"{count} open bug{'' if count == 1 else 's'}. Not in git: it holds Discord messages.",
    ]
    return "\n".join(head) + "".join(f"\n\n{detail_text(*entry)}" for entry in entries) + "\n"
