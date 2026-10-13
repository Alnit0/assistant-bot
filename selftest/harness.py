import asyncio
import json
import logging
import os
import time as stopwatch
import traceback
from contextlib import asynccontextmanager
from datetime import time, timedelta
from pathlib import Path

import discord

from core import cards, clock, config, database, live, llm, occurrences, scheduler
from core import day as days
from core.users import get_user_by_discord_id
from selftest.discordside import Pressed, Seen, Typed, seen

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# What a step of the self-test can do, and how its result is kept.
#
# A step says what it expects in words, does something through the bot's own
# entry points, reads Discord and the database back, and passes or fails with
# what it saw. One step failing never stops the ones after it.
#
# Requests to Claude: a step that needs language gives the words and the
# answer Claude last gave for them (`canned`: recorded in evals/fixtures, or
# written to the same shape). With `claude` on and money left, the words go to
# the real API; otherwise the canned answer is used, and the step says which.
# ---------------------------------------------------------------------------
PASS, FAIL, ERROR, SKIP = "pass", "fail", "error", "skip"
ROUTE_TOOL = "route"
SETTLE = 1.2  # seconds given to Discord and to background work after each input


class Fail(Exception):
    """A step saw something other than what it expected."""


class Harness:
    def __init__(self, main, phase: str, out: Path, claude: bool, budget: float):
        self.main, self.phase, self.out = main, phase, out
        self.claude, self.budget = claude, budget
        self.client: discord.Client = main.client
        self.results: list[dict] = []
        self.typed: set[int] = set()  # the messages posted as "typed by the owner"
        self.memo: dict = {}  # what a later phase needs: message ids, mostly
        self._canned: dict | None = None
        self._real_calls = 0
        self._record: dict | None = None
        self.cut_here = False  # the next request to Claude is where the process dies

    # --- setting up -------------------------------------------------------------------------------------
    async def setup(self) -> None:
        self.inbox = self.client.get_channel(int(config.INBOX_CHANNEL_ID))
        self.hub = self.client.get_channel(int(config.HUB_CHANNEL_ID))
        self.botlog = self.client.get_channel(int(config.BOT_LOG_CHANNEL_ID))
        if None in (self.inbox, self.hub, self.botlog):
            raise RuntimeError("The self-test's channels can't be seen by the bot")
        owner_id = int(config.OWNER_ID)
        guild = self.inbox.guild
        self.owner = guild.get_member(owner_id) or await guild.fetch_member(owner_id)
        self.user = await get_user_by_discord_id(owner_id)
        self._call_tool = llm.call_tool
        llm.call_tool = self._call_tool_or_canned
        # The nightly backup runs for real when the clock passes 3:00 am, into the run's own
        # folder: never into the dev database's backups, where it would push one of them out
        from core import backup

        backup.BACKUP_DIR = self.out.parent / "backups"
        backup.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        # The same for the copies taken before anything is removed (a channel reset, the tidy):
        # the run's own folder, never data/exports
        from tasks import channel

        config.EXPORTS_DIR = channel.EXPORT_DIR = self.out.parent / "exports"

    async def _call_tool_or_canned(self, system, user, tools, *, choice, purpose, task="", max_tokens=600):
        if self.cut_here:
            # As a power cut would: no goodbye, nothing closed, the message left half handled
            self.save()
            await asyncio.sleep(2.5)  # long enough for the 👀 to be on the message
            os._exit(0)
        names = [tool.get("name") for tool in tools]
        canned = self._canned
        if canned is not None:
            if ROUTE_TOOL in names:
                return ROUTE_TOOL, canned["route"]
            return canned["extract"]
        if not self.claude:
            raise RuntimeError(f"A request to Claude ({purpose}) with no canned answer, and real requests are off")
        self._real_calls += 1
        return await self._call_tool(system, user, tools, choice=choice, purpose=purpose, task=task, max_tokens=max_tokens)

    async def spent(self) -> float:
        def total(conn):
            return conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls").fetchone()[0]

        return float(await database.run(total))

    async def can_ask_claude(self) -> bool:
        return self.claude and await self.spent() < self.budget

    # --- steps ------------------------------------------------------------------------------------------
    @asynccontextmanager
    async def step(self, key: str, title: str, expect: str, source: str = ""):
        record = {"phase": self.phase, "key": key, "title": title, "expect": expect, "source": source, "status": PASS, "saw": "", "claude": "", "odd": "", "seconds": 0}
        self._record = record
        began = stopwatch.monotonic()
        try:
            yield record
        except Fail as failed:
            record["status"], record["saw"] = FAIL, str(failed)
        except Exception as error:  # the step itself broke: say where
            where = traceback.extract_tb(error.__traceback__)[-1]
            record["status"] = ERROR
            record["saw"] = f"{error!r} at {Path(where.filename).name}:{where.lineno}"
            log.exception("Self-test step %s broke", key)
        finally:
            record["seconds"] = round(stopwatch.monotonic() - began, 1)
            self._record = None
            self.results.append(record)
            self.save()
            print(f"[{record['status']:5}] {key} {title}" + (f" :: {record['saw'][:200]}" if record["status"] != PASS else ""), flush=True)

    def skip(self, key: str, title: str, why: str, source: str = "") -> None:
        self.results.append({"phase": self.phase, "key": key, "title": title, "expect": "", "source": source, "status": SKIP, "saw": why, "claude": "", "odd": "", "seconds": 0})
        self.save()

    def saw(self, text: str) -> None:
        """What a passing step saw, for the report."""
        if self._record is not None:
            self._record["saw"] = (self._record["saw"] + " · " if self._record["saw"] else "") + text

    def odd(self, text: str) -> None:
        """Something worth a look even though the step passed: it goes under Discoveries."""
        if self._record is not None:
            self._record["odd"] = (self._record["odd"] + " · " if self._record["odd"] else "") + text

    def check(self, condition, saw: str) -> None:
        if not condition:
            raise Fail(saw)

    def save(self) -> None:
        self.out.write_text(json.dumps({"results": self.results, "memo": self.memo}, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- input ------------------------------------------------------------------------------------------
    async def settle(self, seconds: float = SETTLE) -> None:
        await live.settle()
        await asyncio.sleep(seconds)
        await live.settle()

    async def say(self, text: str, channel=None, reply_to: int | None = None, canned=None, task: str = "pills", route: dict | None = None, wait: float = SETTLE) -> int:
        """Type `text` as the owner. `canned` is the extraction Claude would
        return, as (tool, input); with it no request leaves the machine unless
        real requests are on and there is money left."""
        channel = channel or self.inbox
        reference = channel.get_partial_message(reply_to) if reply_to else None
        real = await channel.send(text, reference=reference)
        self.typed.add(real.id)
        use_canned = canned is not None and not await self.can_ask_claude()
        if canned is None and not await self.can_ask_claude():
            pass  # a typed word: it never reaches Claude; if it does, the request is refused and the step fails
        if use_canned:
            self._canned = {
                "route": route or {"kind": "task", "tasks": [task], "confidence": "high", "reports_doing": False, "chat_part": ""},
                "extract": (canned[0], dict(canned[1])),
            }
        if self._record is not None and canned is not None:
            self._record["claude"] = "recorded answer" if use_canned else "real request"
        try:
            await self.main.on_message(Typed(real, self.owner))
        finally:
            self._canned = None
        await self.settle(wait)
        return real.id

    async def press(self, message_id: int, label: str, channel=None, arg: str | None = None) -> Pressed:
        """Press the button whose label has `label` in it, on a real message.
        `arg` picks between buttons with the same label (one a dose on the
        drawn checklist): it is the record's id, the last part of the button's id."""
        channel = channel or self.hub
        self.check(message_id is not None, f"there is no message to press “{label}” on")
        message = await channel.fetch_message(message_id)
        there = seen(message, self.client.user.id)
        fits = [custom_id for said, custom_id in there.buttons if label.lower() in said.lower() and (arg is None or (cards.parse_id(custom_id) or ("", "", "", ""))[3] == arg)]
        # "Taken" is in "Taken at…" too: the shortest label that fits is the one meant
        fits.sort(key=lambda custom_id: len(next(said for said, each in there.buttons if each == custom_id)))
        custom_id = fits[0] if fits else None
        self.check(custom_id is not None, f"no “{label}” button{f' for {arg}' if arg else ''} on the message; it has {there.labels}")
        parsed = cards.parse_id(custom_id)
        self.check(parsed is not None, f"“{label}” is not one of core/cards.py's buttons ({custom_id})")
        _, task, action, arg = parsed
        pressed = Pressed(self.owner, message, custom_id)
        await cards.handle(pressed, task, action, arg)
        await self.settle()
        return pressed

    async def submit(self, pressed: Pressed, **typed: str) -> Pressed:
        """Fill in and send the form a press opened."""
        self.check(pressed.form is not None, f"the press opened no form; it said {pressed.said}")
        form = pressed.form.form
        again = Pressed(self.owner, pressed.message, pressed.form.custom_id)
        await cards.handle(again, form.task, form.action, form.arg, fields=dict(typed))
        await self.settle()
        return again

    # --- the clock --------------------------------------------------------------------------------------
    async def run_due(self) -> None:
        await scheduler.run_all_due()
        await self.settle()
        await scheduler.run_all_due()
        await self.settle(0.5)

    async def clock_to(self, hour: int, minute: int, second: int = 0, day_offset: int = 0) -> None:
        """Move the dev clock ahead to a time of day, and let what came due run."""
        target = days.at(days.today() + timedelta(days=day_offset), time(hour, minute, second))
        if target <= clock.now():
            raise Fail(f"the clock is already past {hour}:{minute:02d}: it reads {config.now_nz():%a %H:%M:%S}")
        clock.advance_to(target)
        await self.run_due()

    async def clock_by(self, minutes: float = 0, seconds: float = 0) -> None:
        clock.advance(timedelta(minutes=minutes, seconds=seconds))
        await self.run_due()

    async def clock_at(self, moment, seconds_after: float = 5) -> None:
        """Move the clock to just after a moment (when a job is due, say)."""
        target = moment + timedelta(seconds=seconds_after)
        if target > clock.now():
            clock.advance_to(target)
        await self.run_due()

    # --- reading back -----------------------------------------------------------------------------------
    async def get(self, channel, message_id: int | None) -> Seen | None:
        if message_id is None:
            return None
        try:
            return seen(await channel.fetch_message(message_id), self.client.user.id)
        except discord.NotFound:
            return None

    async def recent(self, channel, limit: int = 25) -> list[Seen]:
        """The channel's latest messages, newest first."""
        return [seen(message, self.client.user.id) async for message in channel.history(limit=limit)]

    async def find(self, channel, *containing: str, limit: int = 25, typed: bool = False) -> Seen | None:
        """The newest message with every one of these in its text. The words
        the test typed itself are left out unless asked for."""
        for each in await self.recent(channel, limit):
            if (each.id in self.typed) != typed:
                continue
            if all(part in each.all_text for part in containing):
                return each
        return None

    async def count(self, channel, *containing: str, limit: int = 50) -> int:
        return sum(1 for each in await self.recent(channel, limit) if each.id not in self.typed and all(part in each.all_text for part in containing))

    async def doses(self, day_offset: int = 0) -> dict[tuple[str, int], str]:
        """{(pill, dose number): state} for a day, from the database."""
        from tasks.pills import store

        day = days.today() + timedelta(days=day_offset)
        found = await occurrences.for_day(self.user.id, "pills", day)
        names = {pill.id: pill.plan.name for pill in await database.run(store.db_all_pills)}
        return {(names.get(each.item_id, "?"), each.seq): each.state for each in found}

    async def schedules(self) -> list:
        """Every schedule as the engine keeps it (core/timetable.py)."""
        from core import timetable

        return await database.run(timetable.db_all, True)

    async def runs(self, task: str, kind: str) -> list[tuple]:
        """The run log for one kind of job, oldest first: (status, the local time it stands for, its key, its note)."""
        def read(conn):
            return conn.execute(
                "SELECT status, local_at, run_key, note FROM scheduled_jobs WHERE skill = ? AND kind = ? ORDER BY id", (task, kind)
            ).fetchall()

        return await database.run(read)

    async def pills(self) -> dict[str, object]:
        from tasks.pills import store

        return {pill.plan.name: pill for pill in await store.pills(self.user.id)}
