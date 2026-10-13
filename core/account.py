import asyncio
import logging
import os
import sys
import time

import discord

from core import config

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Is this the account it is meant to be?
#
# There are two bots: live (Tanuki) and the dev bot (Testu). A start that
# logged in as the wrong one would answer as it, rename it and write to the
# wrong database's channels (it happened on 2026-10-13: a self-test ran as
# live, beside live). So every start asks Discord who its token is, over HTTP
# only, before anything else: before the lock is taken, before the database
# is opened, before the gateway is connected. The id it expects is
# BOT_USER_ID, in `.env` for live and in `.env.dev` for the dev bot.
#
# Not the expected account, or no expected id set: it logs why and exits,
# having posted, renamed and touched nothing. Once connected it looks once
# more (`still_right`), and disconnects at once if the answer has changed.
# ---------------------------------------------------------------------------
EXIT_WRONG_ACCOUNT = 4
TRIES = 5  # Discord not reachable (the PC has just started): asked again before giving up
WAIT_SECONDS = 5


def mode() -> str:
    """Which bot this start is meant to be, in words."""
    if config.SEPARATE_BOT:
        return "the dev bot (Testu)"
    return "live's account on the dev database" if config.DEV_DATABASE else "live (Tanuki)"


def settings_file() -> str:
    """Where this start's token and expected id come from."""
    return ".env.dev" if config.DEV_ENV else ".env"


def problem(expected: int | None, actual: int | None, name: str = "") -> str:
    """Why this start may not go on, or "" if it is the account it should be."""
    if expected is None:
        return f"BOT_USER_ID is not set in {settings_file()}: without it this start can't tell whether it is {mode()}"
    if actual != expected:
        return f"this start is meant to be {mode()} (id {expected}, BOT_USER_ID in {settings_file()}) but its token logs in as {name or 'another account'} (id {actual})"
    return ""


async def who(token: str) -> tuple[int, str]:
    """The account a token belongs to: (id, name). HTTP only: nothing is
    connected to the gateway, so the account does not come online and
    nothing is received or posted."""
    client = discord.Client(intents=discord.Intents.none())
    try:
        await client.login(token)
        return client.user.id, str(client.user)
    finally:
        await client.close()


def _ask(token: str) -> tuple[int, str]:
    return asyncio.run(who(token))


def check(token: str | None = None) -> None:
    """Before the lock and everything after it: exit unless the token logs in
    as the account this start is meant to be. Blocking: it runs before the
    event loop."""
    expected = config.EXPECTED_BOT_ID
    wrong = problem(expected, expected) if expected is None else ""
    if not wrong:
        actual = None
        for attempt in range(TRIES):
            try:
                actual, name = _ask(token or config.TOKEN)
                break
            except discord.LoginFailure:
                log.error("Not started: Discord refused the token in %s. Nothing was posted or changed.", settings_file())
                sys.exit(EXIT_WRONG_ACCOUNT)
            except (discord.HTTPException, OSError, asyncio.TimeoutError) as error:
                log.warning("Could not ask Discord which account this is (%s), try %d of %d", error, attempt + 1, TRIES)
                if attempt < TRIES - 1:
                    time.sleep(WAIT_SECONDS)
        if actual is None:
            log.error("Not started: Discord could not be asked which account this is. Nothing was posted or changed.")
            sys.exit(1)  # not a wrong account: the service may try again
        wrong = problem(expected, actual, name)
        if not wrong:
            log.info("Account checked before anything else: %s (id %s), as expected for %s", name, actual, mode())
            return
    log.error("Not started: %s. Nothing was posted, renamed or changed, and the lock was not taken.", wrong)
    sys.exit(EXIT_WRONG_ACCOUNT)


def _leave() -> None:
    os._exit(EXIT_WRONG_ACCOUNT)  # at once: no goodbye, nothing closed that could still write


async def still_right(client: discord.Client) -> bool:
    """Once connected, before the bot does its first thing: the account it is
    connected as is still the expected one. If not it disconnects at once,
    logs why and exits. True to go on."""
    user = client.user
    wrong = problem(config.EXPECTED_BOT_ID, getattr(user, "id", None), str(user))
    if not wrong:
        return True
    log.error("Disconnecting: %s. Nothing was posted, renamed or changed.", wrong)
    try:
        await client.close()
    finally:
        _leave()
    return False
