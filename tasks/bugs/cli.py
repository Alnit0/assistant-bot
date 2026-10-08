"""Bugs from the command line, for Claude Code's `bug` skill. Reads and writes
the database directly: the bot isn't started and may be running.

    python -m tasks.bugs.cli list
    python -m tasks.bugs.cli show B4
    python -m tasks.bugs.cli note B4 "fix ready, needs retest: what changed"

A bug is closed by pressing Fixed or Won't fix on its post, never from here.
"""
import sys

from core import database
from core.errors import UserError
from tasks.bugs import rules, store

USAGE = 'Usage: python -m tasks.bugs.cli list | show <id> | note <id> "<text>"'


def run(args: list[str]) -> str:
    """Do what the arguments ask and return what to print. Raises UserError."""
    conn = database.connect()
    try:
        if args == ["list"]:
            return rules.list_text(store._db_open(conn))
        if len(args) >= 2 and args[0] in ("show", "note"):
            item = store._db_get(conn, rules.parse_id(args[1]))
            if item is None:
                raise UserError(f"There is no bug {args[1]}.")
            if args[0] == "show" and len(args) == 2:
                return rules.detail_text(item, store._db_notes(conn, item.id))
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
        print(run(sys.argv[1:]))
    except UserError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
