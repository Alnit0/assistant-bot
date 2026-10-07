import discord

from core import devmode
from core.context import Context
from core.errors import UserError
from core.lifecycle import MessageClass
from skills.base import ANY, Keyword, Param, ReplyAction, Skill
from skills.dev import panel, tools
from skills.dev.panel import PERMISSION
from skills.timers.durations import DurationError, format_duration, parse_duration


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


class DevSkill(Skill):
    """Dev mode: the words, the panel and the tools. The state itself is core/devmode.py."""

    name = "dev"
    description = "Dev mode for testing: shorter waits, debug lines in #bot-log, and inspection tools"

    def tools_available(self, channel_name: str | None) -> bool:
        # Claude only gets the dev tools while testing: dev mode on, or in the dev channel
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
            ),
            word("dev off", "switch dev mode off and restore normal settings", dev_off, ["dev off"], exact=True),
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
            word("dev jobs", "list the scheduler's pending jobs", tools.jobs, ["dev jobs"]),
            setting(
                "dev run",
                "run a background task now",
                tools.run,
                ["dev run backup"],
                "|".join(devmode.TASK_NAMES),
                Param("task", "Which background task to run.", choices=devmode.TASK_NAMES),
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


skill = DevSkill()
