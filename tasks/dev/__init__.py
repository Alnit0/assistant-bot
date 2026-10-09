import discord

from core import clock, devmode, scheduler
from core.config import DEV_DATABASE
from core.context import Context
from core.errors import UserError
from core.lifecycle import MessageClass
from tasks.base import ANY, Keyword, Param, ReplyAction, Task
from tasks.dev import clockwords, panel, tools
from tasks.dev.panel import PERMISSION
from tasks.timers.durations import DurationError, format_duration, parse_duration


DEV_CHANNEL = "dev"  # our name for the scratch channel (DEV_CHANNEL_ID)


# ---------------------------------------------------------------------------
# On, off, and the panel
# ---------------------------------------------------------------------------
async def dev_on(ctx: Context) -> str:
    if devmode.enabled:
        await panel.reshow(ctx.channel_id)
        await ctx.confirm("🛠️ Dev mode is already on.")
        return "already on; panel shown again"
    devmode.enable()
    await panel.started(ctx.channel_id)
    await ctx.confirm("🛠️ Dev mode on.")
    return "dev mode on with the dev defaults"


async def dev_off(ctx: Context) -> str:
    if not devmode.enabled:
        # Asking for what is already so isn't a mistake
        await ctx.confirm("🛠️ Dev mode is already off.")
        return "already off"
    outcome = await panel.stop("`dev off`")
    await ctx.confirm("🛠️ Dev mode off. Normal settings are back.")
    return outcome


MODE_USAGE = "dev mode on|off"


def _is_on_or_off(args: list[str]) -> bool:
    return len(args) == 1 and args[0].lower() in ("on", "off")


async def dev_mode(ctx: Context) -> str:
    """`dev mode on` / `dev mode off`: the switch by its longer name, and the one
    way Claude can turn dev mode on."""
    on = devmode.parse_on_off(ctx.args, MODE_USAGE)
    return await (dev_on(ctx) if on else dev_off(ctx))


async def dev_show(ctx: Context) -> str:
    if not devmode.enabled:
        raise UserError("Dev mode is off. Type `dev on` to start it.")
    await panel.reshow(ctx.channel_id)
    ctx.shown("dev panel")
    return "panel shown again"


async def dev_reset(ctx: Context) -> str:
    return await _set(ctx, devmode.reset, "Dev settings reset to the dev defaults.")


# ---------------------------------------------------------------------------
# Settings. Each one switches dev mode on first if it is off.
# ---------------------------------------------------------------------------
async def _set(ctx: Context, change, done: str) -> str:
    was_on = devmode.enabled
    if not was_on:
        devmode.enable()
    try:
        change()
    except Exception:
        if not was_on:
            devmode.disable()  # a bad value shouldn't leave dev mode half started
        raise
    if was_on:
        await panel.changed()
    else:
        await panel.started(ctx.channel_id)
    await ctx.confirm(f"🛠️ {done}")
    return done + ("" if was_on else " Dev mode switched on.")


async def dev_debounce(ctx: Context) -> str:
    seconds = devmode.parse_number(ctx.args, "dev debounce <seconds>")
    return await _set(ctx, lambda: devmode.set_debounce(seconds), f"Reaction debounce: {seconds:g}s.")


async def dev_speed(ctx: Context) -> str:
    multiplier = devmode.parse_number(ctx.args, "dev speed <n>")
    return await _set(
        ctx, lambda: devmode.set_speed(multiplier), f"Speed: {multiplier:g}x for timers started from now."
    )


async def dev_verbose(ctx: Context) -> str:
    on = devmode.parse_on_off(ctx.args, "dev verbose on|off")
    return await _set(ctx, lambda: devmode.set_verbose(on), f"Verbose log: {'on' if on else 'off'}.")


async def dev_quiet(ctx: Context) -> str:
    # "quiet on" means quiet hours apply, as they normally do
    on = devmode.parse_on_off(ctx.args, "dev quiet on|off")
    return await _set(
        ctx,
        lambda: devmode.set_ignore_quiet_hours(not on),
        f"Quiet hours: {'respected' if on else 'ignored'}.",
    )


async def dev_cleanup(ctx: Context) -> str:
    on = devmode.parse_on_off(ctx.args, "dev cleanup on|off")
    return await _set(
        ctx,
        lambda: devmode.set_cleanup(on),
        "Clean-up: on." if on else "Clean-up: off. Nothing is deleted automatically until `dev cleanup on` or `dev off`.",
    )


async def dev_expire(ctx: Context) -> str:
    try:
        seconds = parse_duration(" ".join(ctx.args))
    except DurationError as error:
        raise UserError(f"{error} Usage: `dev expire <duration>`, e.g. `dev expire 30m`.")
    return await _set(
        ctx, lambda: devmode.set_expiry(seconds), f"Dev mode expires in {format_duration(seconds)}."
    )


# ---------------------------------------------------------------------------
# The clock. Not a dev mode setting: it belongs to the dev database, and stays
# where it is put when dev mode ends, so the records made under it keep
# making sense. Only `dev clock reset` and `dev reset-db` go back.
# ---------------------------------------------------------------------------
LIVE_DATABASE = (
    "That only works on the dev database, so real history is never touched. "
    "Stop the bot and start it with `python main.py --dev`."
)


async def dev_clock(ctx: Context) -> str:
    if not ctx.args:
        said = f"🕰️ Clock: {clockwords.describe(clock.now(), clock.offset())}"
        fixed = "" if DEV_DATABASE else "\n-# It can only be moved on the dev database (`python main.py --dev`)."
        await ctx.reply(said + fixed)
        return said
    if not DEV_DATABASE:
        raise UserError(LIVE_DATABASE)
    moment = clockwords.target(ctx.args, clock.now())
    if moment is None:
        clock.reset()
    else:
        clock.advance_to(moment)
    # Whatever came due on the way runs now, in order
    scheduler.wake()
    if devmode.enabled:
        await panel.changed()
    said = f"Clock: {clockwords.describe(clock.now(), clock.offset())}"
    await ctx.confirm(f"🕰️ {said}")
    return said


class DevTask(Task):
    """Dev mode: the words, the panel and the tools. The state itself is core/devmode.py."""

    name = "dev"
    description = "Dev mode for testing: shorter waits, debug lines in #bot-log, and inspection tools"

    def tools_available(self, channel_name: str | None) -> bool:
        # Claude only gets the dev tools while testing: dev mode on, or in the dev
        # channel. The switch itself (`dev mode`, tool_always) is the exception
        return devmode.enabled or channel_name == DEV_CHANNEL

    def keywords(self) -> list[Keyword]:
        def word(words, description, handler, examples, **options) -> Keyword:
            return Keyword(
                words, description, handler, examples=examples, channels=ANY, permission=PERMISSION, **options
            )

        def setting(words, description, handler, examples, usage, param) -> Keyword:
            return word(words, description, handler, examples, takes_args=True, usage=usage, params=[param])

        return [
            word("dev", "show the dev panel again, at the bottom of this channel", dev_show, ["dev"]),
            word(
                "dev on",
                "switch dev mode on: debounce 2s, speed 1x, verbose on, quiet hours ignored, for 1 hour",
                dev_on,
                ["dev on"],
                tool=False,  # Claude has `dev mode` for both directions
            ),
            word(
                "dev off",
                "switch dev mode off and restore normal settings",
                dev_off,
                ["dev off"],
                exact=True,
                tool=False,
            ),
            word(
                "dev mode",
                "switch dev mode on or off, the same as `dev on` and `dev off`",
                dev_mode,
                ["dev mode on", "dev mode off"],
                takes_args=True,
                usage="on|off",
                accepts=_is_on_or_off,
                params=[Param("state", "on to switch dev mode on, off to switch it off.", choices=("on", "off"))],
                # The one dev tool Claude always has: without it dev mode could
                # never be switched on by asking
                tool_always=True,
            ),
            word("dev reset", "put the dev settings back to the dev defaults", dev_reset, ["dev reset"], exact=True),
            setting(
                "dev debounce",
                "seconds of quiet before reactions are acted on (0 acts at once)",
                dev_debounce,
                ["dev debounce 0", "dev debounce 5"],
                "<seconds>",
                Param("seconds", "Seconds of quiet, from 0 to 600, e.g. 2."),
            ),
            setting(
                "dev speed",
                "make timers and Pomodoro phases run n times faster",
                dev_speed,
                ["dev speed 60"],
                "<n>",
                Param("multiplier", "How many times faster, e.g. 60."),
            ),
            setting(
                "dev verbose",
                "debug cards in #bot-log: the trigger, timings and where reactions ended up",
                dev_verbose,
                ["dev verbose off"],
                "on|off",
                Param("state", "on or off.", choices=("on", "off")),
            ),
            setting(
                "dev quiet",
                "whether quiet hours apply (off means alerts ignore them)",
                dev_quiet,
                ["dev quiet on"],
                "on|off",
                Param("state", "on: quiet hours apply. off: alerts ignore them.", choices=("on", "off")),
            ),
            setting(
                "dev cleanup",
                "whether messages are tidied away by themselves (off keeps every command, "
                "confirmation and alert on screen)",
                dev_cleanup,
                ["dev cleanup off"],
                "on|off",
                Param("state", "off stops all automatic deletion; on brings it back.", choices=("on", "off")),
            ),
            setting(
                "dev expire",
                "switch dev mode off by itself after this long",
                dev_expire,
                ["dev expire 30m", "dev expire 2h"],
                "<duration>",
                Param("duration", "How long from now, e.g. 30m or 2h."),
            ),
            word(
                "dev clock",
                "show the bot's clock, or move it ahead (dev database only): to the next time it reads "
                "a time of day, by a duration, or back to the real time with reset",
                dev_clock,
                ["dev clock", "dev clock 5:59am", "dev clock +2h", "dev clock reset"],
                takes_args=True,
                usage="[<time>|+<duration>|reset]",
                params=[
                    Param(
                        "to",
                        "A time of day (5:59am, 20:00), + and a duration (+2h, +15m), or reset. "
                        "Leave out to show the clock.",
                        required=False,
                    )
                ],
            ),
            word(
                "dev reset-db",
                "wipe the dev database and start it empty, with the clock back at the real time "
                "(dev database only; asks first)",
                tools.reset_db,
                ["dev reset-db"],
                exact=True,
            ),
            word(
                "dev status",
                "say how many copies of the bot are running: the one holding the lock, and any other "
                "process running it (the .venv launcher is not counted)",
                tools.status,
                ["dev status"],
            ),
            word("dev jobs", "list the scheduler's pending jobs", tools.jobs, ["dev jobs"]),
            setting(
                "dev run",
                "run a maintenance routine now",
                tools.run,
                ["dev run backup"],
                "|".join(devmode.ROUTINE_NAMES),
                Param("routine", "Which maintenance routine to run.", choices=devmode.ROUTINE_NAMES),
            ),
            word(
                "dev fire next",
                "run the next pending scheduler job now, whenever it was due",
                tools.fire_next,
                ["dev fire next"],
                exact=True,
            ),
            setting(
                "dev seed",
                f"post n sample messages (up to {tools.MAX_SEED}), tagged as test data",
                tools.seed,
                ["dev seed 5"],
                "<n>",
                Param("count", f"How many sample messages, from 1 to {tools.MAX_SEED}."),
            ),
            word(
                "dev clean",
                "delete the test data and dev tool output in this channel",
                tools.clean,
                ["dev clean"],
                exact=True,
            ),
        ]

    def reply_actions(self) -> list[ReplyAction]:
        return [
            ReplyAction(
                "dev inspect",
                "show what the bot knows about that message: its lifecycle class, pinned, "
                "protected, reactions applied, archive record",
                tools.inspect,
                examples=["dev inspect"],
                permission=PERMISSION,
            ),
        ]

    async def message_class(self, message_id: int) -> MessageClass | None:
        return MessageClass.LIVE if panel.is_panel(message_id) else None

    def setup(self, client: discord.Client) -> None:
        panel.bind(client)
        # Before connecting, so the buttons on a panel from before a restart still answer
        client.add_dynamic_items(panel.PanelButton)

    async def startup(self, client: discord.Client) -> None:
        await panel.clear_stale()
        # On the dev database the status says so from the start
        await panel.show_status()


task = DevTask()
