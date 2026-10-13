"""Run the self-test: `python -m selftest [--full | --stages day,briefing,tidy] [--claude] [--channels | --clear | --remove]`.

With nothing said it runs only the stages touched by what has changed since
each last passed (selftest/stages.py), and says which and why. `--full` is
the whole story: about fifteen minutes, six starts of the dev bot, with 75
seconds off between the first two.

It says how much memory is free before it starts, and stops there when
that is low (`--anyway` goes ahead).

With a dev bot (`.env.dev` has a token of its own) the run is the test
bot's: live is left running, and is never stopped for it. Without one the dev
bot is live's own account, so live must be stopped first, and this refuses to
start while it holds the lock; the status then says "🧪 Self-test running ·
back about <time>" for as long as the run lasts.
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import discord

from core import config, instance_lock
from core.timeinput import format_time
from selftest import bugs, record, report, stages

# ---------------------------------------------------------------------------
# The self-test's own run: channels, the database set aside, a start of the
# dev bot for each phase, the report.
#
# The dev database and the dev clock that are there are moved aside first and
# put back at the end, so the run starts from an empty database and leaves
# the user's own dev data as it was.
# ---------------------------------------------------------------------------
CATEGORY = "selftest"
CHANNELS = {"hub": "selftest-hub", "inbox": "selftest-inbox", "bot-log": "selftest-log"}
FORUM = "selftest-bugs"  # the dev bot's own forum for its bugs, so it never posts in the real one
ENV_NAMES = {"hub": "HUB_CHANNEL_ID", "inbox": "INBOX_CHANNEL_ID", "bot-log": "BOT_LOG_CHANNEL_ID", "bugs": "BUGS_CHANNEL_ID"}


def separate() -> bool:
    """Whether there is a dev bot: a second Discord account, which runs the
    self-test while live carries on."""
    return config.test_bot_token() is not None


def token() -> str:
    """The token the run's own calls to Discord are made with: the dev bot's
    when there is one. Never printed."""
    return config.test_bot_token() or config.TOKEN


def confirm_account(client) -> None:
    """The launcher's own calls (finding, emptying and writing in the
    self-test's channels) are the dev bot's when there is one: refuse to make
    them as anyone else."""
    if separate() and client.user.id != config.test_bot_id():
        raise RuntimeError(f"the self-test's own calls would be made as {client.user} (id {client.user.id}), not the dev bot (BOT_USER_ID in .env.dev)")


def back_about(now: datetime, minutes: float) -> str:
    """When live is expected back, for the status of a run that stopped it: "4:15 pm"."""
    return format_time((now + timedelta(minutes=minutes + 2)).time())
WORK = config.DATA_DIR / "selftest"
DEV_FILES = ("dev.db", "dev.db-wal", "dev.db-shm", "dev-clock.json")
OFF_FOR = 75  # seconds the bot stays off between the phase that is cut off and the next: a job is late after 60
PHASE_TIMEOUT = 20 * 60
PASSED = WORK / "passed.json"  # {stage: the commit it last passed on}
HISTORY = WORK / "history.csv"  # a line a run, only ever added to (selftest/record.py)
BUGS = WORK / "bugs.json"  # {step: the dev bug it has} (selftest/bugs.py)

# (name, the settings it starts with, seconds to stay off before it)
PHASES = (
    ("p1", {"CARDS_V2": "false", "REMINDERS_ENABLED": "true"}, 0),
    ("p2", {"CARDS_V2": "false", "REMINDERS_ENABLED": "true"}, OFF_FOR),
    ("p3", {"CARDS_V2": "true", "REMINDERS_ENABLED": "true"}, 0),
    ("p4", {"CARDS_V2": "false", "REMINDERS_ENABLED": "true", "DAILY_SPEND_LIMIT": "0.001"}, 0),
    ("p5", {"CARDS_V2": "true", "REMINDERS_ENABLED": "true", "BRIEFING_ENABLED": "true"}, 0),
    ("p6", {"CARDS_V2": "true", "REMINDERS_ENABLED": "true", "BRIEFING_ENABLED": "true", "HUB_TIDY": "true"}, 0),
)


async def prepare_channels(purge: bool = True) -> dict[str, int]:
    """Find or make the self-test's category and channels, over HTTP only (no
    gateway connection, so this never disturbs a running bot), and empty them."""
    client = discord.Client(intents=discord.Intents.none())
    await client.login(token())
    try:
        confirm_account(client)
        inbox = await client.fetch_channel(int(config.INBOX_CHANNEL_ID))
        guild = await client.fetch_guild(inbox.guild.id)
        existing = await guild.fetch_channels()
        category = next((each for each in existing if isinstance(each, discord.CategoryChannel) and each.name == CATEGORY), None)
        if category is None:
            category = await guild.create_category(CATEGORY, reason="The bot's self-test")
        found: dict[str, int] = {}
        for role, name in CHANNELS.items():
            channel = next((each for each in existing if isinstance(each, discord.TextChannel) and each.name == name), None)
            if channel is None:
                channel = await guild.create_text_channel(name, category=category, reason="The bot's self-test", topic="Written and emptied by the bot's self-test (python -m selftest). Nothing here is real.")
            elif purge:
                # Everything goes but the summaries of earlier runs: they are the record that stays
                going = [message async for message in channel.history(limit=None) if not (message.content or "").startswith(record.MARK)]
                for start in range(0, len(going), 100):
                    batch = going[start:start + 100]
                    recent = [message for message in batch if (discord.utils.utcnow() - message.created_at).days < 13]
                    # One that has gone meanwhile (a line that deletes itself) is what was wanted
                    try:
                        if len(recent) > 1:
                            await channel.delete_messages(recent)
                    except discord.NotFound:
                        recent = []
                    for message in batch if len(recent) <= 1 else [each for each in batch if each not in recent]:
                        try:
                            await message.delete()
                        except discord.NotFound:
                            pass
            found[role] = channel.id
        if separate():
            # The dev bot's bugs get a forum of their own, never emptied: the posts are the record
            forum = next((each for each in existing if isinstance(each, discord.ForumChannel) and each.name == FORUM), None)
            if forum is None:
                forum = await guild.create_forum(FORUM, category=category, reason="The bot's self-test", topic="Bugs the bot's self-test found (python -m selftest). A step that fails gets a post; it is marked Fixed when the step passes again.")
            found["bugs"] = forum.id
        return found
    finally:
        await client.close()


async def remove_channels() -> list[str]:
    """Delete the self-test's channels and its category. Over HTTP only."""
    client = discord.Client(intents=discord.Intents.none())
    await client.login(token())
    try:
        inbox = await client.fetch_channel(int(config.INBOX_CHANNEL_ID))
        guild = await client.fetch_guild(inbox.guild.id)
        existing = await guild.fetch_channels()
        gone = []
        for each in existing:
            ours = isinstance(each, discord.TextChannel) and each.name in CHANNELS.values()
            if ours or (isinstance(each, discord.ForumChannel) and each.name == FORUM):
                await each.delete(reason="The bot's self-test, removed on request")
                gone.append(f"#{each.name}")
        for each in existing:
            if isinstance(each, discord.CategoryChannel) and each.name == CATEGORY:
                await each.delete(reason="The bot's self-test, removed on request")
                gone.append(f"the category {each.name}")
        return gone
    finally:
        await client.close()


def set_aside(stamp: str) -> Path | None:
    """Move the dev database and clock out of the way. Returns where they went."""
    there = [config.DATA_DIR / name for name in DEV_FILES if (config.DATA_DIR / name).exists()]
    if not there:
        return None
    saved = WORK / f"saved-{stamp}"
    saved.mkdir(parents=True, exist_ok=True)
    for path in there:
        shutil.move(str(path), str(saved / path.name))
    return saved


def put_back(saved: Path | None, stamp: str) -> None:
    """Keep the self-test's database for looking at, and restore what was set aside."""
    kept = WORK / f"run-{stamp}"
    kept.mkdir(parents=True, exist_ok=True)
    for name in DEV_FILES:
        path = config.DATA_DIR / name
        if path.exists():
            shutil.move(str(path), str(kept / name))
    if saved is not None:
        for path in saved.iterdir():
            shutil.move(str(path), str(config.DATA_DIR / path.name))
        saved.rmdir()


def results_of(folder: Path) -> list[dict]:
    """The steps a run recorded, start by start, from what it left in its folder."""
    found = []
    for path in sorted(folder.glob("p*.json")):
        try:
            found += json.loads(path.read_text(encoding="utf-8")).get("results", [])
        except (OSError, ValueError):
            pass
    return found


def recover() -> list[dict]:
    """A run that was stopped before its end (the PC was low on memory, the
    window was closed) left the dev database set aside and no line of history.
    Put the database back, keep what the run had got to, and record it as not
    finished. Returns the lines added."""
    added = []
    for saved in sorted(WORK.glob("saved-*")):
        if not saved.is_dir():
            continue
        stamp = saved.name[len("saved-"):]
        spent = report.spent(config.DATA_DIR / "dev.db")  # the stopped run's own database is still in the way
        put_back(saved, stamp)
        (WORK / f"run-{stamp}" / record.UNFINISHED_FILE).write_text(record.UNFINISHED, encoding="utf-8")  # kept as long as a run with a failure
        line = record.row(stamp, "", "?", results_of(WORK / f"run-{stamp}"), spent, False, 0, note=record.UNFINISHED)
        record.append(HISTORY, line)
        added.append(line)
    return added


async def say(channel_id: int, text: str) -> None:
    """One message in a channel, over HTTP only."""
    client = discord.Client(intents=discord.Intents.none())
    await client.login(token())
    try:
        confirm_account(client)
        channel = await client.fetch_channel(channel_id)
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
    finally:
        await client.close()


def file_bugs(line: dict, results: list[dict], stamp: str, channel_id: int) -> tuple[list[str], str]:
    """Bring the bugs up to date with a run, in a process of its own on the dev
    database (it is back in its place by now). Returns (a line a bug touched,
    what went wrong if anything did). With nothing failed and no bug on record
    there is nothing to do, and nothing is started."""
    if not record.failed_steps(results) and not bugs.has_known(BUGS):
        return [], ""
    source = WORK / f"run-{stamp}" / "results.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    kept = [{name: each.get(name, "") for name in ("phase", "key", "title", "expect", "saw", "status")} for each in results]
    source.write_text(json.dumps({"date": line["date"], "commit": line["commit"], "channel_id": channel_id, "results": kept}, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        done = subprocess.run(
            [sys.executable, "-m", "selftest.bugs", "--dev", str(source)], cwd=config.BASE_DIR, capture_output=True, text=True, encoding="utf-8",
            timeout=300, env={**config.environment_for_child(), "PYTHONIOENCODING": "utf-8", **({"DISCORD_TOKEN": token()} if separate() else {})},
        )
    except subprocess.TimeoutExpired:
        return [], "the bugs were not brought up to date: it took too long"
    lines = []
    for each in done.stdout.splitlines():
        try:
            act = json.loads(each)
        except ValueError:
            continue
        lines.append(bugs.line(act["what"], act["bug"] or "no bug", act["step"], act.get("url"), act.get("after") or ()))
    problem = "" if done.returncode == 0 else f"the bugs were not brought up to date: {(done.stderr or '').strip().splitlines()[-1][:200] if (done.stderr or '').strip() else 'exit ' + str(done.returncode)}"
    return lines, problem


def prune_runs(today: str) -> list[str]:
    """Take out the run folders that are no longer kept (`record.old_runs`):
    the last ten stay, and one with a failure, or that never finished, for 30
    days. Only `run-<stamp>` folders of the self-test's own are ever removed."""
    runs = []
    for folder in WORK.glob("run-*"):
        if folder.is_dir():
            failed = bool(record.failed_steps(results_of(folder))) or (folder / record.UNFINISHED_FILE).exists()
            runs.append((folder.name[len("run-"):], failed))
    gone = []
    for stamp in record.old_runs(runs, today):
        try:
            shutil.rmtree(WORK / f"run-{stamp}")
            gone.append(stamp)
        except OSError as error:
            print(f"--- the old run folder run-{stamp} could not be removed: {error}", flush=True)
    return gone


def keep(line: dict, results: list[dict], stamp: str, channels: dict[str, int]) -> None:
    """What lasts of a run: its line of history, the table in the report, a
    bug a failing step, and one message in #selftest-log. Each by itself: one
    that can't be done is said, and the others are still done."""
    try:
        record.append(HISTORY, line)
        record.put_view(report.PATH, record.read(HISTORY))
    except OSError as error:
        print(f"--- the history could not be written: {error}", flush=True)
    try:
        touched, problem = file_bugs(line, results, stamp, channels.get("bot-log", 0))
    except Exception as error:
        touched, problem = [], f"the bugs were not brought up to date: {error}"
    for each in touched:
        print(f"--- bug: {each}", flush=True)
    if problem:
        print(f"--- {problem}", flush=True)
    try:
        asyncio.run(say(channels["bot-log"], record.summary(line, touched, problem)))
    except Exception as error:
        print(f"--- the summary could not be posted in #selftest-log: {error}", flush=True)
    gone = prune_runs(stamp[:8])
    if gone:
        print(f"--- {len(gone)} old run folder{'' if len(gone) == 1 else 's'} removed (the last {record.KEEP_RUNS} are kept, and one with a failure for {record.KEEP_FAILED_DAYS} days)", flush=True)


def run_phase(name: str, settings: dict, channels: dict[str, int], claude: bool, budget: float, memo: dict, stamp: str) -> dict:
    out = WORK / f"run-{stamp}" / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Never this process's own environment: it has read .env, so live's token is in it, and a
    # start that inherited that would log in as live. The start reads the files for itself
    env = config.environment_for_child()
    env.update(settings)
    env["SELFTEST_SEPARATE"] = "1" if separate() else "0"
    if separate():
        env["DISCORD_TOKEN"] = token()  # the dev bot's, handed over explicitly: never left to what is inherited
    if os.environ.get("SELFTEST_BACK"):
        env["SELFTEST_BACK"] = os.environ["SELFTEST_BACK"]
    env.update({ENV_NAMES[role]: str(channel_id) for role, channel_id in channels.items()})
    env.update({"SELFTEST": "1", "SELFTEST_CLAUDE": "1" if claude else "0", "SELFTEST_BUDGET": str(budget), "SELFTEST_MEMO": json.dumps(memo), "KEEP_CONFIRMATIONS": "true", "PYTHONIOENCODING": "utf-8", "COMMANDS_CHANNEL_ID": ""})  # and live's #commands is not rewritten by the test
    started = time.monotonic()
    try:
        done = subprocess.run([sys.executable, "-m", "selftest.phase", "--dev", name, str(out)], env=env, cwd=config.BASE_DIR, timeout=PHASE_TIMEOUT)
        code = done.returncode
    except subprocess.TimeoutExpired:
        code = -1
    found = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"results": [], "memo": {}}
    found["exit"], found["seconds"] = code, round(time.monotonic() - started)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m selftest")
    parser.add_argument("--claude", action="store_true", help="send the language steps to the real API (within --budget)")
    parser.add_argument("--budget", type=float, default=0.20, help="stop sending real requests once this much is spent (US$)")
    parser.add_argument("--full", action="store_true", help="the whole run, every stage")
    parser.add_argument("--stages", default="", help="the stages to run: day, briefing, tidy (tidy runs the briefing's start too)")
    parser.add_argument("--anyway", action="store_true", help="go ahead although free memory is low")
    parser.add_argument("--only", default="", help="starts to run, e.g. p1,p2 (for working on the test itself)")
    parser.add_argument("--channels", action="store_true", help="only find or make the channels, and say their ids")
    parser.add_argument("--clear", action="store_true", help="only empty the self-test's channels")
    parser.add_argument("--remove", action="store_true", help="only delete the self-test's channels and category")
    asked = parser.parse_args()

    if asked.clear:
        print("Emptied:", asyncio.run(prepare_channels(purge=True)))
        return 0
    if asked.remove:
        print("Deleted:", ", ".join(asyncio.run(remove_channels())) or "nothing: they were not there")
        return 0

    if asked.channels:
        print(asyncio.run(prepare_channels(purge=False)))
        return 0
    if separate():
        held = instance_lock.holder(instance_lock.TEST_LOCK)
        if held is not None:
            print(f"The dev bot is already running (PID {held.pid}). Stop it first: the self-test starts it itself.")
            return 3
        print("--- the dev bot runs this (.env.dev has a token of its own): live is left running", flush=True)
    else:
        held = instance_lock.holder(instance_lock.LIVE_LOCK)
        if held is not None:
            print(f"A bot is running (PID {held.pid}), and there is no dev bot (.env.dev has no token of its own), so the self-test would use the same account. Stop it first.")
            return 3
        print("--- there is no dev bot: this runs as live's own account, with live stopped", flush=True)

    wanted = [name.strip() for name in asked.only.split(",") if name.strip()]
    named = [name.strip() for name in asked.stages.split(",") if name.strip()]
    unknown = [name for name in named if name not in stages.STAGES]
    if unknown:
        print(f"No such stage: {', '.join(unknown)}. The stages are {', '.join(stages.ORDER)}.")
        return 2
    passed = stages.read_passed(PASSED)
    if asked.full:
        chosen = list(stages.ORDER)
        print("--- the full run, as asked", flush=True)
    elif named:
        chosen = [stage for stage in stages.ORDER if stage in named]
        print(f"--- the stages asked for: {', '.join(chosen)}", flush=True)
    elif wanted:
        chosen = []
    else:
        why = stages.touched({stage: stages.changed_since(config.BASE_DIR, passed.get(stage)) for stage in stages.ORDER})
        chosen = list(why)
        for stage in stages.ORDER:
            print(f"--- {stage}: {'run, touched by ' + why[stage] if stage in why else 'not run, nothing that touches it has changed since it passed'}", flush=True)
        if not chosen:
            print("--- nothing to run. `--full` runs everything all the same.")
            return 0
    if not wanted:
        wanted = stages.phases_for(chosen)
    whole = set(wanted) == {name for name, _, _ in PHASES}
    minutes = sum(stages.ABOUT_MINUTES.get(name, 2) for name in wanted) + (OFF_FOR / 60 if {"p1", "p2"} <= set(wanted) else 0)
    low, line = stages.memory_line(stages.free_memory())
    print(f"--- {line}", flush=True)
    if low and not asked.anyway:
        print("--- not started. Close something and ask again, or `--anyway` to go ahead.")
        return 4

    for line in recover():
        print(f"--- the run of {line['date']} did not finish: the dev database it had set aside is back in its place, and it is in the history", flush=True)
    began = datetime.now()
    stamp = began.strftime("%Y%m%d-%H%M%S")
    commit = stages.head(config.BASE_DIR)
    print(f"--- starts {', '.join(wanted)}: about {round(minutes)} minutes", flush=True)
    if not separate():
        # Live is off for this: the account's status says so, and when it is expected back
        os.environ["SELFTEST_BACK"] = back_about(began, minutes)
    channels = asyncio.run(prepare_channels())
    saved = set_aside(stamp)
    phases, memo = [], {}
    try:
        for name, settings, off_for in PHASES:
            if wanted and name not in wanted:
                continue
            if off_for and phases:
                print(f"--- the bot stays off for {off_for}s before {name}", flush=True)
                time.sleep(off_for)
            print(f"--- {name} {settings}", flush=True)
            found = run_phase(name, settings, channels, asked.claude, asked.budget, memo, stamp)
            memo = found.get("memo", memo)
            phases.append((name, settings, found))
    finally:
        spent = report.spent(config.DATA_DIR / "dev.db")
        put_back(saved, stamp)
    path = report.write(phases, spent, asked.claude, stamp, partial=not whole, began=began, ended=datetime.now(), ran=", ".join(chosen) if chosen and not whole else "")
    results = [each for _, _, found in phases for each in found["results"]]
    bad = [each for each in results if each["status"] in ("fail", "error")]
    ran = "full" if whole else ", ".join(chosen) or "starts " + ",".join(wanted)
    keep(record.row(stamp, commit, ran, results, spent, asked.claude, int((datetime.now() - began).total_seconds())), results, stamp, channels)
    # A stage that ran whole with nothing failed has passed on this commit: it is not run again until something touches it
    failed = {name for name, _, found in phases if found.get("exit") != 0 or any(each["status"] in ("fail", "error") for each in found["results"])}
    if commit:
        for stage in stages.passed_stages([name for name, _, _ in phases], failed):
            passed[stage] = commit
        stages.write_passed(PASSED, passed)
    print(f"--- {len(results)} steps, {len(bad)} failed, US${spent:.4f} spent. Report: {path}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
