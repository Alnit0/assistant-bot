import asyncio
import logging
import time

from core import cards, lifecycle, outgoing, surface, tidy
from core.cards import Card
from tasks.base import ANY, Keyword
from tasks.lab import grid, ratelimits

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# "lab grid [seconds]" (behind LAB_GRID, off): the 5 by 5 grid of
# tasks/lab/grid.py, one message edited frame by frame. The lab may use
# discord.py, but this goes through the door (core/surface.py) as new code
# would: the post and every edit.
#
# One edit at a time: a frame's wait starts once the edit before it has
# returned, so edits never pile up. An edit that fails, or that Discord
# rate-limits, stops it at once: the message is left as it is and no frame
# is tried again. discord.py waits out a 429 and sends it again by itself,
# and says so only in its log: the lab's monitor (tasks/lab/ratelimits.py)
# counts those, and one counted during an edit is that edit rate-limited.
# What a run measured goes to the log only, never to a channel.
# ---------------------------------------------------------------------------
BUSY = "🧪 A grid is already running: one at a time."
lock = grid.OneAtATime()
last: grid.Run | None = None  # the last run's measurements, for the self-test's check
_running: set[asyncio.Task] = set()


async def animate(channel_id: int, seconds: float) -> grid.Run:
    """Post frame 0, then edit it through frames 1 to 9; the measurements. Holds the lock while it runs."""
    global last
    run = grid.Run(seconds)
    last = run
    try:
        message_id = await surface.send(channel_id, outgoing.clean(grid.frame_text(0)) or grid.frame_text(0), silent=True)
    except surface.Failed as problem:
        run.failed += 1
        run.frames = 0
        log.info("lab grid: the first frame could not be posted (%s)", problem.status or problem)
        return run
    if message_id is None:
        run.frames = 0
        return run
    returned = time.perf_counter()
    for frame in range(1, grid.LAST + 1):
        await asyncio.sleep(seconds)
        limited_before = ratelimits.monitor.count
        try:
            await surface.edit(channel_id, message_id, outgoing.clean(grid.frame_text(frame)) or grid.frame_text(frame))
        except surface.Failed as problem:
            run.failed += 1
            log.info("lab grid: frame %s could not be drawn (%s): stopped there", frame, problem.status or problem)
            break
        now = time.perf_counter()
        run.gaps.append(now - returned)
        returned = now
        run.frames += 1
        if ratelimits.monitor.count > limited_before:
            run.limited += 1
            log.info("lab grid: frame %s was rate-limited: stopped there", frame)
            break
    return run


async def _run(channel_id: int, seconds: float) -> None:
    try:
        run = await animate(channel_id, seconds)
        log.info(run.line())
    except Exception:
        log.exception("lab grid: the run failed")
    finally:
        lock.release()


async def run_grid(ctx) -> str:
    """ "lab grid", "lab grid 0.5": the grid, animated in this channel. One at a time across the bot."""
    seconds = grid.seconds(ctx.args[0] if ctx.args else None)
    if not lock.take():
        note = await cards.send(ctx.channel_id, Card(BUSY), silent=True)
        await tidy.later(ctx.channel_id, note, lifecycle.delete_after())
        return "a grid is running already"
    # Its own asyncio task: the typed word is answered at once, and the grid runs on its own time
    going = asyncio.get_running_loop().create_task(_run(ctx.channel_id, seconds))
    _running.add(going)
    going.add_done_callback(_running.discard)
    return f"grid started, {seconds:.1f}s a frame"


KEYWORDS = [
    Keyword(
        "lab grid",
        "a 5 by 5 grid of coloured squares, animated by editing one message: a proof of concept. "
        f"Seconds between frames, {grid.FASTEST} to {grid.SLOWEST} (1.0 if not said)",
        run_grid,
        examples=["lab grid", "lab grid 0.5"],
        channels=ANY,
        permission="lab",
        takes_args=True,
        usage="[seconds]",
        exact=True,
    ),
]
