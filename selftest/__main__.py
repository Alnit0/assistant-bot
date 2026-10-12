"""Run the self-test: `python -m selftest [--claude] [--only p1,p2] [--channels | --clear | --remove]`.

A full run takes about nine minutes: four starts of the dev bot, with 75
seconds off between the first two.

The live bot must be stopped first: it and the dev bot share one token. This
refuses to start while any copy holds the lock.
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import discord

from core import config, instance_lock
from selftest import report

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
ENV_NAMES = {"hub": "HUB_CHANNEL_ID", "inbox": "INBOX_CHANNEL_ID", "bot-log": "BOT_LOG_CHANNEL_ID"}
WORK = config.DATA_DIR / "selftest"
DEV_FILES = ("dev.db", "dev.db-wal", "dev.db-shm", "dev-clock.json")
OFF_FOR = 75  # seconds the bot stays off between the phase that is cut off and the next: a job is late after 60
PHASE_TIMEOUT = 20 * 60

# (name, the settings it starts with, seconds to stay off before it)
PHASES = (
    ("p1", {"CARDS_V2": "false", "REMINDERS_ENABLED": "true"}, 0),
    ("p2", {"CARDS_V2": "false", "REMINDERS_ENABLED": "true"}, OFF_FOR),
    ("p3", {"CARDS_V2": "true", "REMINDERS_ENABLED": "true"}, 0),
    ("p4", {"CARDS_V2": "false", "REMINDERS_ENABLED": "true", "DAILY_SPEND_LIMIT": "0.0001"}, 0),
)


async def prepare_channels(purge: bool = True) -> dict[str, int]:
    """Find or make the self-test's category and channels, over HTTP only (no
    gateway connection, so this never disturbs a running bot), and empty them."""
    client = discord.Client(intents=discord.Intents.none())
    await client.login(config.TOKEN)
    try:
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
                while True:
                    batch = [message async for message in channel.history(limit=100)]
                    if not batch:
                        break
                    recent = [message for message in batch if (discord.utils.utcnow() - message.created_at).days < 13]
                    if len(recent) > 1:
                        await channel.delete_messages(recent)
                    for message in batch if len(recent) <= 1 else [each for each in batch if each not in recent]:
                        await message.delete()
            found[role] = channel.id
        return found
    finally:
        await client.close()


async def remove_channels() -> list[str]:
    """Delete the self-test's channels and its category. Over HTTP only."""
    client = discord.Client(intents=discord.Intents.none())
    await client.login(config.TOKEN)
    try:
        inbox = await client.fetch_channel(int(config.INBOX_CHANNEL_ID))
        guild = await client.fetch_guild(inbox.guild.id)
        existing = await guild.fetch_channels()
        gone = []
        for each in existing:
            if isinstance(each, discord.TextChannel) and each.name in CHANNELS.values():
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


def run_phase(name: str, settings: dict, channels: dict[str, int], claude: bool, budget: float, memo: dict, stamp: str) -> dict:
    out = WORK / f"run-{stamp}" / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(settings)
    env.update({ENV_NAMES[role]: str(channel_id) for role, channel_id in channels.items()})
    env.update({"SELFTEST": "1", "SELFTEST_CLAUDE": "1" if claude else "0", "SELFTEST_BUDGET": str(budget), "SELFTEST_MEMO": json.dumps(memo), "KEEP_CONFIRMATIONS": "true", "PYTHONIOENCODING": "utf-8"})
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
    parser.add_argument("--only", default="", help="phases to run, e.g. p1,p2 (for working on the test itself)")
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
    held = instance_lock.holder()
    if held is not None:
        print(f"A bot is running (PID {held.pid}). Stop it first: the self-test uses the same token.")
        return 3

    began = datetime.now()
    stamp = began.strftime("%Y%m%d-%H%M%S")
    print("--- the self-test takes about nine minutes: four starts of the dev bot, 75 seconds off between the first two", flush=True)
    channels = asyncio.run(prepare_channels())
    saved = set_aside(stamp)
    wanted = [name.strip() for name in asked.only.split(",") if name.strip()]
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
    path = report.write(phases, spent, asked.claude, stamp, partial=bool(wanted), began=began, ended=datetime.now())
    results = [each for _, _, found in phases for each in found["results"]]
    bad = [each for each in results if each["status"] in ("fail", "error")]
    print(f"--- {len(results)} steps, {len(bad)} failed, US${spent:.4f} spent. Report: {path}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
