import json
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures for the router and for extraction: a sentence, and what it must
# come out as. One JSON file per task in evals/fixtures/, plus general.json
# for the traps that belong to no task.
#
#   "router":     message (+ what is on screen)  -> the task(s), a tie, or chat
#   "extraction": task + message (+ state, card) -> the action, its data, what
#                 was guessed
#
# Each fixture may carry `recorded`: what Claude actually returned the last
# time the live eval was run with --record. The ordinary tests replay that
# through the code that checks and reads it, so they need no network and
# cost nothing; the live eval (python -m evals.live --live) asks the real
# API and says how often it is right and what that costs.
#
# Add a fixture for every example in a task's spec and for every bug found
# in QA. No Discord, no database, no API here.
# ---------------------------------------------------------------------------
FOLDER = Path(__file__).resolve().parent / "fixtures"


@dataclass
class RouterFixture:
    file: str
    message: str
    tasks: list[str] = field(default_factory=list)  # expected, in any order; empty with chat
    tie: bool = False
    chat: bool = False
    # With tasks: whether part of the message is for no task and must be answered as chat too
    also_chat: bool = False
    on_screen: str = ""
    note: str = ""
    # Why the model is known to get this one wrong, if it does. It still counts
    # against the accuracy; the ordinary tests check it is still a miss, so a
    # model that starts getting it right is noticed
    known_miss: str = ""
    recorded: dict | None = None

    @property
    def name(self) -> str:
        return f"{self.file}: {self.message}"


@dataclass
class ExtractionFixture:
    file: str
    task: str
    message: str
    action: str  # expected; "none" or "not_this" for those
    data: dict = field(default_factory=dict)  # every key here must come back with this value
    guessed: list[str] | None = None  # exactly these, if given
    state: str = ""
    card: dict | None = None  # {"action":…, "data":…, "guessed":[…], "said":…} for a follow-up
    note: str = ""
    known_miss: str = ""
    recorded: list | None = None  # [tool name, input]

    @property
    def name(self) -> str:
        return f"{self.file}: {self.message}"


def load() -> tuple[list[RouterFixture], list[ExtractionFixture]]:
    routers, extractions = [], []
    for path in sorted(FOLDER.glob("*.json")):
        content = json.loads(path.read_text(encoding="utf-8"))
        routers += [RouterFixture(path.stem, **entry) for entry in content.get("router", [])]
        extractions += [ExtractionFixture(path.stem, **entry) for entry in content.get("extraction", [])]
    return routers, extractions


def save_recorded(routers: list[RouterFixture], extractions: list[ExtractionFixture]) -> None:
    """Write what Claude returned back into the fixture files, beside what was expected."""
    for path in sorted(FOLDER.glob("*.json")):
        content = json.loads(path.read_text(encoding="utf-8"))
        for kind, fixtures in (("router", routers), ("extraction", extractions)):
            by_message = {fixture.message: fixture for fixture in fixtures if fixture.file == path.stem}
            for entry in content.get(kind, []):
                fixture = by_message.get(entry["message"])
                if fixture is not None and fixture.recorded is not None:
                    entry["recorded"] = fixture.recorded
        path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Does what came back match what was expected? (pure)
# ---------------------------------------------------------------------------
def _same(expected, actual) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(_same(a, b) for a, b in zip(expected, actual))
    return expected == actual


def router_problem(fixture: RouterFixture, route) -> str:
    """What is wrong with a Route for this fixture, or "" if it is right."""
    if fixture.chat:
        return "" if route.chat else f"expected chat, got {list(route.tasks)}"
    if route.chat:
        return f"expected {fixture.tasks}, got chat"
    if sorted(route.tasks) != sorted(fixture.tasks):
        return f"expected {fixture.tasks}, got {list(route.tasks)}"
    if route.tie != fixture.tie:
        return f"expected {'a tie' if fixture.tie else 'no tie'}, got {'a tie' if route.tie else 'no tie'}"
    if bool(route.chat_part) != fixture.also_chat:
        if fixture.also_chat:
            return "expected a chat part as well, got none"
        return f"expected no chat part, got {route.chat_part!r}"
    return ""


def extraction_problem(fixture: ExtractionFixture, found) -> str:
    """What is wrong with an Extracted for this fixture, or "" if it is right."""
    got = "not_this" if found.not_this else (found.action.name if found.action else "none")
    if got != fixture.action:
        return f"expected {fixture.action}, got {got}" + (f" ({found.reason})" if found.reason else "")
    if found.action is None:
        return ""
    for name, expected in fixture.data.items():
        if name not in found.data:
            return f"`{name}` is missing (expected {expected!r})"
        if not _same(expected, found.data[name]):
            return f"`{name}` is {found.data[name]!r}, expected {expected!r}"
    if fixture.guessed is not None and sorted(found.guessed) != sorted(fixture.guessed):
        return f"guessed {sorted(found.guessed)}, expected {sorted(fixture.guessed)}"
    return ""
