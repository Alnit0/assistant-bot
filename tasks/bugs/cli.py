"""Bugs from the command line, for Claude Code's `bug` skill. Reads and writes
the database directly: the bot isn't started and may be running.

    python -m tasks.bugs.cli list
    python -m tasks.bugs.cli show B4
    python -m tasks.bugs.cli note B4 "fix ready, needs retest: what changed"
    python -m tasks.bugs.cli shipped B4 tests/test_golden.py::test_name [more tests] [--with <python>]

`shipped` is run in live's folder once a fix is live: for a bug I reported, it
checks that the golden tests named replay my own messages from the report word
for word and pass on the code live runs, then marks the bug: it closes by
itself in three days unless I say reopen or report it again. Live's own
Python has no pytest (it is for development machines only): `--with` names
one that has it, the work folder's, and the tests still run on this folder's
code.

A bug of the dev database has a D in front (D4) and needs `--dev`, which picks
that database:

    python -m tasks.bugs.cli show D4 --dev

A bug is never closed from here: Fixed or Won't fix on its post, close B4 in
words, or by itself three days after `shipped`.
"""
import ast
import subprocess
import sys

from core import config, database
from core import day as days
from core.errors import UserError
from tasks.bugs import rules, store

USAGE = 'Usage: python -m tasks.bugs.cli list | show <id> | note <id> "<text>" | shipped <id> <golden test>...'
GOLDEN = "tests/test_golden.py"
LIVE_MARK = "live-versions.txt"  # in live's data folder only: the update script writes it


def _test_code(node: str) -> str:
    """A golden test's own code, its decorators with it (the messages it replays may be parameters)."""
    path, _, name = node.partition("::")
    if path.replace("\\", "/") != GOLDEN or not name:
        raise UserError(f"{node} isn't a golden test: name one in {GOLDEN}, as {GOLDEN}::test_name")
    source = (config.BASE_DIR / GOLDEN).read_text(encoding="utf-8")
    bare = name.split("[")[0]
    for each in ast.walk(ast.parse(source)):
        if isinstance(each, ast.FunctionDef) and each.name == bare:
            start = min([each.lineno, *(decorator.lineno for decorator in each.decorator_list)])
            return "\n".join(source.splitlines()[start - 1:each.end_lineno])
    raise UserError(f"There is no {bare} in {GOLDEN}.")


def _passes(nodes: list[str], python: str = "") -> bool:
    """The tests run on the code of this folder (live's), by `python -m pytest` from here, so this
    folder's code is what is imported: True only if every one passes."""
    python = python or sys.executable
    if subprocess.run([python, "-c", "import pytest"], cwd=config.BASE_DIR, capture_output=True).returncode != 0:
        raise UserError("That Python has no pytest: name one that has it with --with <python> (the work folder's .venv).")
    done = subprocess.run([python, "-m", "pytest", "-q", *nodes], cwd=config.BASE_DIR, capture_output=True, text=True)
    return done.returncode == 0


def _with(args: list[str]) -> tuple[list[str], str]:
    """The arguments without `--with <python>`, and that Python ("" for this one)."""
    if "--with" not in args:
        return args, ""
    at = args.index("--with")
    if at + 1 >= len(args):
        raise UserError("--with needs a Python: the path of one that has pytest.")
    return args[:at] + args[at + 2:], args[at + 1]


def _commit() -> str:
    done = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.BASE_DIR, capture_output=True, text=True)
    return done.stdout.strip() or "this folder's commit"


def shipped(conn, args: list[str]) -> str:
    if not (config.DATA_DIR / LIVE_MARK).exists() or config.DEV_DATABASE:
        raise UserError("Run this in live's folder, on live's database: the fix must be what live runs.")
    args, python = _with(args)
    item = store._db_get(conn, rules.parse_id(args[0]))
    nodes = args[1:]
    if item is None:
        raise UserError(f"There is no bug {args[0]}.")
    name = rules.bug_id(item.id)
    if item.status != rules.OPEN:
        raise UserError(f"{name} is closed already.")
    if item.report.source not in rules.MINE:
        raise UserError(f"{name} wasn't reported by you: only a bug you reported closes by itself.")
    if not nodes:
        raise UserError(f"Name the golden test that replays the messages of {name}.")
    code = "\n".join(_test_code(node) for node in nodes)
    missing = rules.uncovered(rules.owner_words(item.report), code)
    if missing:
        raise UserError(f"{len(missing)} of your messages in {name} {'is' if len(missing) == 1 else 'are'} not replayed word for word by the tests named.")
    if not _passes(nodes, python):
        raise UserError(f"The tests named don't pass on this folder's code: {name} is not marked.")
    on = rules.closes_on(days.today())
    store._db_mark_shipped(conn, item.id, on.isoformat(), " ".join(nodes))
    store._db_add_note(conn, item.id, item.user_id, rules.CLAUDE_CODE, rules.shipped_note(_commit(), nodes, on, item.id))
    conn.commit()
    return f"{name}: fix shipped, closes by itself on {on:%a} {on.day} {on:%b} (its post is told at the bot's next 9:00 am round)."


def run(args: list[str]) -> str:
    """Do what the arguments ask and return what to print. Raises UserError."""
    conn = database.connect()
    try:
        if args == ["list"]:
            return rules.list_text(store._db_open(conn))
        if len(args) >= 2 and args[0] == "shipped":
            return shipped(conn, args[1:])
        if len(args) >= 2 and args[0] in ("show", "note"):
            item = store._db_get(conn, rules.parse_id(args[1]))
            if item is None:
                raise UserError(f"There is no bug {args[1]}.")
            if args[0] == "show" and len(args) == 2:
                return rules.detail_text(item, store._db_notes(conn, item.id), store._db_events(conn, item.id))
            text = " ".join(args[2:]).strip()
            if args[0] == "note" and text:
                store._db_add_note(conn, item.id, item.user_id, rules.CLAUDE_CODE, text)
                conn.commit()
                return f"Note added to {rules.bug_id(item.id)}."
        raise UserError(USAGE)
    finally:
        conn.close()


def main() -> int:
    # Messages carry emoji, which a Windows console's default encoding can't print
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        # `--dev` has already picked the database (core/config.py); it is not an argument here
        print(run([arg for arg in sys.argv[1:] if arg != "--dev"]))
    except UserError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
