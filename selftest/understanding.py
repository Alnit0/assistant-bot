"""The cross-task understanding checks, replayed in every self-test run (nightly too).

    python -m selftest.understanding <out.json>     (started by `python -m selftest`)

The 44 cross-task golden conversations (evals/fixtures/crosstask.json, recorded from the real
router and extraction on 15 Oct) are read back as Claude last answered them, through the bot's
own code that reads and checks those answers (core/routing.py, core/extraction.py), and judged as
the ordinary tests judge them (evals/fixtures.py). Nothing is sent to Claude, no bot is started,
and no database is opened. The ordinary test run does the same, and the end-to-end conversations
built on them (tests/test_golden_crosstask.py); this is the part that needs no test tools, so it
runs from live's own folder at night. One step in the run's report; a failure names the
conversations that failed, and is a dev bug like any step's.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

NAME = "understanding"
WORDS = "The cross-task conversations, as Claude last answered them (offline: no request sent, no bot started)"
# The golden conversations across tasks (15 Oct) and those of the newer tasks against the older (16 Oct)
FILES = ("crosstask", "spanning", "calendar_write", "diary", "reading")
TIMEOUT = 120


def every_entry() -> list:
    """Every real task, with the ones behind a switch on while the catalogue is read: their fixtures are replayed too."""
    from core import actions, config
    from tasks import registry

    for name in ("BRIEFING_ENABLED", "WEATHER_ENABLED", "DAY_QUESTIONS", "TODOS_ENABLED", "NUDGES_ENABLED", "HABITS_ENABLED", "CALENDAR_ENABLED", "DIARY_ENABLED", "READING_ENABLED", "PLAN_MY_DAY", "BIRTHDAYS_ENABLED", "GYM_ENABLED", "GYM_WEIGHT", "BEDTIME_ENABLED"):
        setattr(config, name, True)
    # The calendar's writing, with a made-up Bot calendar, only while the catalogue is read: put back at
    # once, so the dev bot itself never reads or writes a calendar it was not given
    writing = (config.CALENDAR_WRITE, config.CALENDAR_BOT_ID)
    config.CALENDAR_WRITE, config.CALENDAR_BOT_ID = True, "made-up-bot@group.calendar.example"
    try:
        registry.load()
        return actions.catalogue()
    finally:
        config.CALENDAR_WRITE, config.CALENDAR_BOT_ID = writing


def judged(entries: list) -> tuple[int, list[str]]:
    """(how many recorded answers were read back, "x9: gym at 6 (the problem)" for each that is wrong now)."""
    from core import extraction, routing
    from evals import fixtures

    names = [entry.name for entry in entries]
    routers, extractions = fixtures.load()
    ran, bad = 0, []
    for fixture in (each for each in routers if each.file in FILES):
        if fixture.recorded is None or set(fixture.tasks) - set(names):
            bad.append(f"{fixture.golden}: {fixture.message} (not recorded, or its task is not loaded)")
            continue
        ran += 1
        problem = fixtures.router_problem(fixture, fixtures.settled(fixture, routing.parse(fixture.recorded, names), entries))
        if problem and not fixture.known_miss:
            bad.append(f"{fixture.golden}: {fixture.message} ({problem})")
    for fixture in (each for each in extractions if each.file in FILES):
        entry = next((each for each in entries if each.name == fixture.task), None)
        if fixture.recorded is None or entry is None:
            bad.append(f"{fixture.golden}: {fixture.message} (not recorded, or its task is not loaded)")
            continue
        ran += 1
        found = extraction.read(entry, tuple(fixture.recorded), follow_up=fixture.card is not None or fixture.after_list or fixture.after_answer or fixture.replied)
        problem = fixtures.extraction_problem(fixture, found)
        if problem and not fixture.known_miss:
            bad.append(f"{fixture.golden}: {fixture.message} ({problem})")
    return ran, bad


def step(ran: int, bad: list[str], problem: str = "") -> dict:
    """The run's one step for the replay."""
    status = "error" if problem else "fail" if bad or not ran else "pass"
    saw = problem or ("; ".join(bad[:6]) + (f"; and {len(bad) - 6} more" if len(bad) > 6 else "") if bad else f"{ran} recorded answers read back right" if ran else "nothing was found to read back")
    return {
        "phase": NAME, "key": "u.01", "title": "The cross-task conversations, as last recorded", "status": status, "saw": saw, "claude": "recorded answer", "odd": "", "seconds": 0,
        "expect": "Every cross-task golden conversation reads as it did when recorded: the router's task and extraction's action, as the bot's own code reads them",
        "source": "asked (15 Oct): the cross-task golden conversations",
    }


def run(folder: Path) -> dict:
    """The replay, in a process of its own, as a start of the self-test's own: {"results": [one step], "exit": 0, "seconds": n}."""
    from core import config

    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "understanding.json"
    began = time.monotonic()
    try:
        subprocess.run(
            [sys.executable, "-m", "selftest.understanding", str(out)], cwd=config.BASE_DIR, capture_output=True, text=True, encoding="utf-8",
            timeout=TIMEOUT, env={**config.environment_for_child(), "PYTHONIOENCODING": "utf-8"},
        )
        found = json.loads(out.read_text(encoding="utf-8"))
    except (subprocess.TimeoutExpired, OSError, ValueError) as error:
        found = step(0, [], f"the replay could not be run: {type(error).__name__}")
    found["seconds"] = round(time.monotonic() - began, 1)
    return {"results": [found], "exit": 0, "seconds": round(time.monotonic() - began)}


def main() -> int:
    out = Path(sys.argv[1])
    try:
        found = step(*judged(every_entry()))
    except Exception as error:  # the replay itself broke: say so, as a step that broke
        found = step(0, [], f"the replay broke: {error!r}"[:300])
    out.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
