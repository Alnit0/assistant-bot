"""What lasts of a self-test run: one line of history, and the words of its summary.

    data/selftest/history.csv   a line a run, only ever added to
    docs/SELFTEST.md            the latest of them, as a short table

No Discord and no bot here, so all of it is tested offline. A step that
failed also becomes a bug (selftest/bugs.py).
"""
import csv
from pathlib import Path

FIELDS = ("date", "commit", "ran", "steps", "passed", "failed", "failed_steps", "spend_usd", "claude", "seconds", "note")
BAD = ("fail", "error")
SHOWN = 15  # runs in the table in docs/SELFTEST.md; all of them are in the file
START, END = "<!-- run history: written by python -m selftest -->", "<!-- end of run history -->"
UNFINISHED = "did not finish: stopped before the end"
MARK = "🧪 Self-test"  # how a summary in #selftest-log begins: the emptying before a run leaves these


KEEP_RUNS = 10  # run folders kept whatever they hold
KEEP_FAILED_DAYS = 30  # and one with a failure in it, for this long
UNFINISHED_FILE = "unfinished.txt"  # left in the folder of a run that was stopped before its end


def old_runs(runs: list[tuple[str, bool]], today: str) -> list[str]:
    """The run folders that may go. `runs` is (the run's stamp, whether a step
    failed in it or it never finished); `today` a stamp's first eight digits.
    The latest ten stay whatever they hold, and one with a failure stays for
    30 days from its run."""
    from datetime import date

    def day(stamp: str) -> date:
        return date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))

    going = []
    for stamp, failed in sorted(runs, reverse=True)[KEEP_RUNS:]:
        try:
            age = (day(today) - day(stamp)).days
        except ValueError:
            continue  # not a run's stamp: not ours to judge
        if not failed or age > KEEP_FAILED_DAYS:
            going.append(stamp)
    return sorted(going)


def failed_steps(results: list[dict]) -> list[str]:
    return [each["key"] for each in results if each["status"] in BAD]


def row(stamp: str, commit: str | None, ran: str, results: list[dict], spent: float, claude: bool, seconds: int, note: str = "") -> dict:
    """One run as its line of history. `stamp` is the run's own (20261013-152146)."""
    bad = failed_steps(results)
    return {
        "date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]}",
        "commit": (commit or "")[:7],
        "ran": ran,
        "steps": str(len(results)),
        "passed": str(sum(1 for each in results if each["status"] == "pass")),
        "failed": str(len(bad)),
        "failed_steps": " ".join(bad),
        "spend_usd": f"{spent:.4f}",
        "claude": "real" if claude else "recorded",
        "seconds": str(int(seconds)),
        "note": note,
    }


def append(path: Path, line: dict) -> None:
    """Add a run to the history. The file is only ever added to: nothing in it
    is rewritten, and the heading is written once, when the file is made."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS, extrasaction="ignore")
        if fresh:
            writer.writeheader()
        writer.writerow({name: line.get(name, "") for name in FIELDS})


def read(path: Path) -> list[dict]:
    """Every run on record, oldest first. A file that is not there is no runs."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as source:
        return [dict(each) for each in csv.DictReader(source)]


def _minutes(seconds: str) -> str:
    try:
        whole = int(float(seconds))
    except ValueError:
        return ""
    return f"{whole // 60} min {whole % 60:02d} s"


def view(rows: list[dict], shown: int = SHOWN) -> list[str]:
    """The latest runs as a table, newest first."""
    lines = ["## Run history", ""]
    if not rows:
        return lines + ["No run on record yet.", ""]
    lines += [
        f"The latest {min(shown, len(rows))} of {len(rows)} runs, newest first. All of them, a line a run, are in",
        "`data/selftest/history.csv` (never rewritten). The first step to fail in a stage is a bug in the forum until it passes again.",
        "",
        "| Run | Commit | What ran | Passed | Failed | Failed steps | Spend | Took |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for each in list(reversed(rows))[:shown]:
        failed = each.get("failed", "0")
        what = each.get("ran", "") + (f" ({each['note']})" if each.get("note") else "")
        lines.append(
            f"| {each.get('date', '')} | `{each.get('commit') or '?'}` | {what} | {each.get('passed', '')} of {each.get('steps', '')} | "
            f"{'**' + failed + '**' if failed not in ('0', '') else '0'} | {each.get('failed_steps') or '·'} | "
            f"US${each.get('spend_usd', '')}{'' if each.get('claude') == 'real' else ' (recorded)'} | {_minutes(each.get('seconds', ''))} |"
        )
    return lines + [""]


def with_view(document: str, rows: list[dict]) -> str:
    """The report with the history table in it: in place of the one that is
    there, or before "What failed" in a report that has none yet."""
    block = "\n".join([START, *view(rows), END])
    if START in document and END in document:
        before, rest = document.split(START, 1)
        return before + block + rest.split(END, 1)[1]
    anchor = "## What failed"
    if anchor in document:
        at = document.index(anchor)
        return document[:at] + block + "\n\n" + document[at:]
    return document.rstrip("\n") + "\n\n" + block + "\n"


def put_view(path: Path, rows: list[dict]) -> None:
    """Bring the table in docs/SELFTEST.md up to date, whatever kind of run this was."""
    document = path.read_bytes().decode("utf-8").replace("\r\n", "\n") if path.exists() else "# Self-test\n"
    path.write_bytes(with_view(document, rows).replace("\n", "\r\n").encode("utf-8"))


def summary(line: dict, bugs: list[str] = (), problem: str = "") -> str:
    """The one message a run leaves in #selftest-log."""
    failed = line["failed"] not in ("0", "")
    head = f"{MARK} · {line['date']} · {line['ran']} · commit `{line['commit'] or '?'}`"
    if line.get("note"):
        result = f"⚠️ {line['note']} ({line['passed']} of {line['steps']} steps had passed)"
    elif failed:
        result = f"❌ {line['failed']} of {line['steps']} steps failed: {line['failed_steps']}"
    else:
        result = f"✅ {line['passed']} of {line['steps']} steps passed"
    spend = f"US${line['spend_usd']} spent" + ("" if line["claude"] == "real" else " (recorded answers)")
    parts = [head, f"{result} · {spend} · {_minutes(line['seconds'])}"]
    parts += [f"🐞 {each}" for each in bugs]
    if problem:
        parts.append(f"⚠️ {problem}")
    return "\n".join(parts)[:1900]
