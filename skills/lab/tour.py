import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

import discord

from core import database
from core.config import REACTION_DEBOUNCE_SECONDS
from core.discord_utils import safe_reply
from skills.lab import common
from skills.lab.common import (
    Run,
    check_owner,
    lab_keyword,
    record,
    record_press,
    report_component_error,
)

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# lab tour: a guided run through the interactive tests
#
# One card, edited in place, walks through the steps below. Most steps notice
# by themselves when the thing being tested has happened (the rest of the bot
# reports in through on_action and on_label). The run lives in the database,
# so it carries on after a restart.
# ---------------------------------------------------------------------------
PASS, FAIL, SKIP = "pass", "fail", "skip"
ICONS = {PASS: "✅", FAIL: "❌", SKIP: "⏭️"}
NOTE_LIMIT = 200


@dataclass(frozen=True)
class Check:
    key: str  # what the rest of the bot reports
    label: str  # what the card says


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    instructions: str
    checks: tuple[Check, ...]
    auto_pass: bool  # pass by itself once every check is ticked (else the user judges)


STEPS: tuple[Step, ...] = (
    Step(
        "shortcut",
        "Plain-word shortcut",
        "In #inbox, type `ping` (or `stats`). It should answer, and your message should disappear.",
        (Check("word", "a plain word ran"),),
        auto_pass=True,
    ),
    Step(
        "buttons",
        "Buttons",
        "Type `lab buttons`. On the first message: press **Count**, flip a toggle, "
        "choose from a select menu, and fill in the **Form**.",
        (
            Check("counter", "counter pressed"),
            Check("toggle", "toggle flipped"),
            Check("select", "select menu used"),
            Check("form", "form submitted"),
        ),
        auto_pass=True,
    ),
    Step(
        "reactions",
        "Reactions and debounce",
        "Type `lab react`, add and remove a few reactions on its message, then leave it "
        "alone for 15 seconds. It should turn into a summary and get ✅.",
        (Check("settled", "quiet period ended and the summary was posted"),),
        auto_pass=True,
    ),
    Step(
        "reply_archive",
        "Reply “archive”, with clean-up",
        "Post any message, then reply to it with `archive`. It should move to the archive "
        "channel, your reply should vanish, and “📦 Archived” should show briefly.",
        (
            Check("archived", "archive succeeded"),
            Check("reply_cleaned", "your reply was cleaned up"),
        ),
        auto_pass=True,
    ),
    Step(
        "box",
        "📦 reaction archive",
        "Post another message and react to it with 📦. It should be archived after "
        f"{REACTION_DEBOUNCE_SECONDS} seconds.",
        (Check("box_archived", "📦 archived the message"),),
        auto_pass=True,
    ),
    Step(
        "dashboard",
        "Pinned dashboard",
        "Type `lab pin`. A status message should be pinned and change on the minute. "
        "Type `lab pin stop` once you've seen it update.",
        (
            Check("pin_started", "status message pinned"),
            Check("pin_updated", "it updated itself"),
        ),
        auto_pass=False,
    ),
    Step(
        "chart",
        "Chart",
        "Type `lab chart`. Two charts should appear and be readable on your phone.",
        (Check("chart", "charts posted"),),
        auto_pass=False,
    ),
    Step(
        "chat",
        "Claude chat and reset",
        "In #inbox, send Claude any message and wait for the answer, then type `reset`.",
        (
            Check("chat", "Claude answered"),
            Check("reset", "memory cleared afterwards"),
        ),
        auto_pass=True,
    ),
)

# What the lab's own log labels mean to the tour
LABEL_SIGNALS = {
    "buttons: counter": "counter",
    "buttons: alerts toggle": "toggle",
    "buttons: quiet hours toggle": "toggle",
    "buttons: single select": "select",
    "buttons: multi select": "select",
    "buttons: form submitted": "form",
    "react: settled": "settled",
    "status: updated": "pin_updated",
}


@dataclass
class Result:
    status: str
    auto: bool = False
    note: str = ""


@dataclass
class TourRun:
    id: int
    user_id: int | None
    channel_id: int
    message_id: int | None = None
    step: int = 0
    detected: set[str] = field(default_factory=set)
    results: dict[str, Result] = field(default_factory=dict)

    @property
    def finished(self) -> bool:
        return self.step >= len(STEPS)


_active: TourRun | None = None
_client: discord.Client | None = None
# One change to the run at a time: button presses and detections can arrive together
_lock = asyncio.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Database (blocking; called through database.run)
# ---------------------------------------------------------------------------
def _db_create(conn: sqlite3.Connection, user_id: int | None, channel_id: int) -> int:
    cursor = conn.execute(
        "INSERT INTO lab_tour_runs (user_id, channel_id, started_at) VALUES (?, ?, ?)",
        (user_id, channel_id, _now()),
    )
    return cursor.lastrowid


def _db_save(conn: sqlite3.Connection, run: TourRun) -> None:
    conn.execute(
        "UPDATE lab_tour_runs SET channel_id = ?, message_id = ?, current_step = ?, detected = ? WHERE id = ?",
        (run.channel_id, run.message_id, run.step, json.dumps(sorted(run.detected)), run.id),
    )


def _db_save_result(conn: sqlite3.Connection, run: TourRun, step_key: str) -> None:
    result = run.results[step_key]
    conn.execute(
        """
        INSERT INTO lab_tour_results (run_id, step, status, auto, note, user_id, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, step) DO UPDATE SET
            status = excluded.status, auto = excluded.auto, note = excluded.note,
            recorded_at = excluded.recorded_at
        """,
        (run.id, step_key, result.status, int(result.auto), result.note, run.user_id, _now()),
    )


def _db_finish(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("UPDATE lab_tour_runs SET finished_at = ? WHERE id = ?", (_now(), run_id))


def _db_load_active(conn: sqlite3.Connection) -> TourRun | None:
    row = conn.execute(
        """
        SELECT id, user_id, channel_id, message_id, current_step, detected
        FROM lab_tour_runs WHERE finished_at IS NULL ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    run = TourRun(row[0], row[1], row[2], row[3], row[4], set(json.loads(row[5])))
    for step, status, auto, note in conn.execute(
        "SELECT step, status, auto, note FROM lab_tour_results WHERE run_id = ?", (run.id,)
    ):
        run.results[step] = Result(status, bool(auto), note or "")
    return run


# ---------------------------------------------------------------------------
# What the card says
# ---------------------------------------------------------------------------
def progress_lines(run: TourRun, final: bool = False) -> list[str]:
    lines = []
    for index, step in enumerate(STEPS):
        result = run.results.get(step.key)
        if index == run.step and not final:
            icon, extra = "▶️", ""
        elif result is None:
            icon, extra = "▫️", " (not run)" if final else ""
        else:
            icon = ICONS[result.status]
            extra = " (detected)" if result.auto else ""
            if result.note:
                extra += f": {result.note}"
        lines.append(f"{icon} {step.title}{extra}")
    return lines


def render_card(run: TourRun) -> discord.Embed:
    step = STEPS[run.step]
    embed = discord.Embed(
        title=f"🧭 Lab tour · step {run.step + 1} of {len(STEPS)}: {step.title}",
        description=step.instructions,
        colour=discord.Colour.blurple(),
    )
    checks = "\n".join(
        f"{'✅' if check.key in run.detected else '⬜'} {check.label}" for check in step.checks
    )
    hint = (
        "Passes by itself once every box is ticked."
        if step.auto_pass
        else "Press **Pass** when it looks right to you."
    )
    embed.add_field(name="Checked automatically", value=f"{checks}\n-# {hint}", inline=False)
    embed.add_field(name="Progress", value="\n".join(progress_lines(run)), inline=False)
    embed.set_footer(text=f"Run {run.id} · type “lab tour” to bring this card back down")
    return embed


def tally(run: TourRun) -> str:
    counts = {status: 0 for status in (PASS, FAIL, SKIP)}
    for result in run.results.values():
        counts[result.status] += 1
    not_run = len(STEPS) - len(run.results)
    text = f"{counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped"
    return text + (f", {not_run} not run" if not_run else "")


def render_summary(run: TourRun, stopped: bool) -> discord.Embed:
    failed = any(result.status == FAIL for result in run.results.values())
    embed = discord.Embed(
        title=f"🧭 Lab tour {'stopped' if stopped else 'finished'}: {tally(run)}",
        description="\n".join(progress_lines(run, final=True)),
        colour=discord.Colour.red() if failed else discord.Colour.green(),
    )
    embed.set_footer(text=f"Run {run.id} · results saved · type “lab tour” to start another")
    return embed


# ---------------------------------------------------------------------------
# Changing the run. Callers hold _lock.
# ---------------------------------------------------------------------------
async def _deliver(run: TourRun, embed: discord.Embed, view, interaction=None) -> None:
    """Show the card: as the answer to a button press, or by editing the message."""
    if interaction is not None:
        await interaction.response.edit_message(embed=embed, view=view)
        return
    channel = _client.get_channel(run.channel_id) if _client else None
    if channel is None:
        log.warning("Tour card channel not found; the card was not updated")
        return
    try:
        await channel.get_partial_message(run.message_id).edit(embed=embed, view=view)
    except discord.NotFound:
        # The card was deleted: put it back
        message = await (channel.send(embed=embed, view=view) if view else channel.send(embed=embed))
        run.message_id = message.id
        if not run.finished:
            await database.run(_db_save, run)
    except discord.HTTPException as error:
        log.warning("Could not update the tour card: %s", error)


async def _show(run: TourRun, interaction=None, stopped: bool = False) -> None:
    """Show where the run is now, finishing it if the last step is done."""
    global _active
    if not (run.finished or stopped):
        await _deliver(run, render_card(run), TourView(), interaction)
        return

    await database.run(_db_finish, run.id)
    _active = None
    await _deliver(run, render_summary(run, stopped), None, interaction)
    await record(
        f"tour {'stopped' if stopped else 'finished'}: {tally(run)}",
        "\n".join(progress_lines(run, final=True)),
        channel_id=run.channel_id,
        user_id=run.user_id,
        message_id=run.message_id,
    )


async def _set_result(run: TourRun, status: str, auto: bool, note: str = "") -> None:
    """Record the current step's result and move to the next step."""
    step = STEPS[run.step]
    run.results[step.key] = Result(status, auto, note[:NOTE_LIMIT])
    run.step += 1
    run.detected = set()
    await database.run(_db_save_result, run, step.key)
    await database.run(_db_save, run)


# ---------------------------------------------------------------------------
# Noticing that a test has been done
# ---------------------------------------------------------------------------
async def signal(key: str) -> None:
    """Something the tour may be waiting for has happened."""
    async with _lock:
        run = _active
        if run is None or run.finished:
            return
        step = STEPS[run.step]
        if key not in {check.key for check in step.checks} or key in run.detected:
            return
        # The reset only counts once Claude has answered something
        if key == "reset" and "chat" not in run.detected:
            return

        run.detected.add(key)
        complete = all(check.key in run.detected for check in step.checks)
        if complete and step.auto_pass:
            await _set_result(run, PASS, auto=True)
        else:
            await database.run(_db_save, run)
        await _show(run)


async def on_label(label: str) -> None:
    """The lab logged something (see common.observers)."""
    key = LABEL_SIGNALS.get(label)
    if key is not None:
        await signal(key)


async def on_action(result) -> None:
    """A word, reply action, reaction or chat finished (the "action_finished" event)."""
    run = _active
    if run is None or result.status != "ok" or result.user_id != run.user_id:
        return
    if result.kind == "command":
        if result.name == "lab chart":
            await signal("chart")
        elif result.name == "lab pin" and result.reply.startswith("pinned"):
            await signal("pin_started")
        elif result.name == "reset":
            await signal("reset")
        elif not result.name.startswith("lab "):
            await signal("word")
    elif result.kind == "reply_action" and result.name == "archive":
        await signal("archived")
        if result.command_deleted:
            await signal("reply_cleaned")
    elif result.kind == "reaction" and result.name == "📦":
        await signal("box_archived")
    elif result.kind == "chat":
        await signal("chat")


# ---------------------------------------------------------------------------
# The card's buttons (persistent, so they work after a restart)
# ---------------------------------------------------------------------------
async def _current(interaction: discord.Interaction) -> TourRun | None:
    """The run this card belongs to, or None (after telling the user why not)."""
    if _active is None:
        await safe_reply(interaction, "No tour is running. Type `lab tour` to start one.")
        return None
    if interaction.message is None or interaction.message.id != _active.message_id:
        await safe_reply(
            interaction, "This card is out of date. Type `lab tour` to bring the current one down."
        )
        return None
    return _active


async def _press(interaction: discord.Interaction, status: str, note: str = "") -> None:
    async with _lock:
        run = await _current(interaction)
        if run is None:
            return
        step = STEPS[run.step]
        await _set_result(run, status, auto=False, note=note)
        await _show(run, interaction)
    await record_press(interaction, f"tour: {step.key} {status}", note or step.title)


class FailNote(discord.ui.Modal, title="What went wrong?"):
    note = discord.ui.TextInput(
        label="Short note",
        placeholder="e.g. the reply wasn't deleted",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=NOTE_LIMIT,
    )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_component_error(interaction, error, "tour: fail note")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await check_owner(interaction):
            return
        await _press(interaction, FAIL, note=self.note.value.strip())


class TourView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await check_owner(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        await report_component_error(interaction, error, "tour")

    @discord.ui.button(label="Pass", emoji="✅", style=discord.ButtonStyle.success, custom_id="lab:tour:pass")
    async def passed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _press(interaction, PASS)

    @discord.ui.button(label="Fail", emoji="❌", style=discord.ButtonStyle.danger, custom_id="lab:tour:fail")
    async def failed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _current(interaction) is not None:
            await interaction.response.send_modal(FailNote())

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="lab:tour:skip")
    async def skipped(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _press(interaction, SKIP)

    @discord.ui.button(label="Back", emoji="↩️", style=discord.ButtonStyle.secondary, custom_id="lab:tour:back")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with _lock:
            run = await _current(interaction)
            if run is None:
                return
            if run.step == 0:
                await safe_reply(interaction, "This is the first step.")
                return
            run.step -= 1
            run.detected = set()
            await database.run(_db_save, run)
            await _show(run, interaction)
        await record_press(interaction, "tour: back", f"back to {STEPS[run.step].title}")

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.secondary, custom_id="lab:tour:stop")
    async def stop_tour(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with _lock:
            run = await _current(interaction)
            if run is None:
                return
            await _show(run, interaction, stopped=True)
        await record_press(interaction, "tour: stop", "stopped early")


def register(client: discord.Client) -> None:
    """Before connecting: make the card's buttons work on messages from before a restart."""
    client.add_view(TourView())
    if on_label not in common.observers:
        common.observers.append(on_label)


async def resume(client: discord.Client) -> None:
    """At startup: pick up a run that was in progress."""
    global _active, _client
    _client = client
    _active = await database.run(_db_load_active)
    if _active is not None:
        log.info("Resumed lab tour run %s at step %s", _active.id, _active.step + 1)


# ---------------------------------------------------------------------------
# lab tour [new|stop]
# ---------------------------------------------------------------------------
async def run_tour(run: Run, action: str) -> None:
    global _active
    await run.start()
    async with _lock:
        active = _active

        if action == "stop":
            if active is None:
                run.note("no tour was running")
                await run.done("No tour is running.")
                return
            await _show(active, stopped=True)
            run.note(f"stopped tour run {active.id}")
            await run.done("Tour stopped. The summary is in #bot-log.")
            return

        if action == "new" and active is not None:
            await _show(active, stopped=True)
            active = None

        if active is not None:
            # Carry on: move the card down to where the user is now
            old_channel = _client.get_channel(active.channel_id) if _client else None
            if old_channel is not None and active.message_id is not None:
                try:
                    await old_channel.get_partial_message(active.message_id).delete()
                except discord.HTTPException:
                    pass
            active.channel_id = run.channel.id
            message = await run.channel.send(embed=render_card(active), view=TourView())
            active.message_id = message.id
            await database.run(_db_save, active)
            run.note(f"moved the tour card (run {active.id}, step {active.step + 1})")
            await run.done(f"Tour card moved here: step {active.step + 1} of {len(STEPS)}.")
            return

        run_id = await database.run(_db_create, run.user_id, run.channel.id)
        active = TourRun(run_id, run.user_id, run.channel.id)
        message = await run.channel.send(embed=render_card(active), view=TourView())
        active.message_id = message.id
        await database.run(_db_save, active)
        _active = active
        run.note(f"started tour run {run_id}")
        await run.done("Tour started. Follow the card; it updates as you go.")


KEYWORDS = [
    lab_keyword(
        "lab tour",
        "a guided run through the interactive tests on one card, with Pass, Fail and Skip; "
        "type it again to carry on where you left off",
        run_tour,
        usage="[new|stop]",
        parse=lambda args: (args.choice(["new", "stop", "resume"], default="resume"),),
        examples=["lab tour", "lab tour new", "lab tour stop"],
    ),
]
