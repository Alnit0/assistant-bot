"""One start of the dev bot with the self-test's steps run inside it.

    python -m selftest.phase --dev <phase> <results.json>

Started by `python -m selftest`, never by hand: the channels and the settings
come from the environment it sets. `--dev` is read by core/config.py, so this is
the dev database or nothing.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path


def main() -> int:
    name, out = sys.argv[2], Path(sys.argv[3])
    from core import config

    if not config.DEV_DATABASE:
        print("The self-test only runs on the dev database (--dev).")
        return 2
    if os.getenv("SELFTEST") != "1":
        print("Start the self-test with `python -m selftest`.")
        return 2
    if os.getenv("SELFTEST_SEPARATE") == "1" and not config.SEPARATE_BOT:
        # The run was told it is the dev bot's, and this start would log in as someone else
        print("Not started: this would not log in with the dev bot's token (.env.dev), and live is running.")
        return 2

    import main as bot
    from core import account, instance_lock
    from core.logging_setup import setup_logging
    from core.migrations import migrate
    from core.users import ensure_owner
    from selftest import phases
    from selftest.harness import Harness
    from tasks import registry

    setup_logging()
    log = logging.getLogger("assistant")
    log.info("Self-test phase %s: the dev database %s", name, config.DB_PATH.name)
    # As any start of the bot: the account first, then the lock (core/account.py)
    account.check(config.TOKEN)
    instance_lock.acquire()
    registry.load()
    migrate(registry.task_migrations())
    ensure_owner()

    ready = asyncio.Event()
    started = bot.on_ready

    @bot.client.event
    async def on_ready():
        print(f"--- logged in as {bot.client.user} (id {bot.client.user.id}): {'the dev bot' if config.SEPARATE_BOT else 'the account in .env'}", flush=True)
        await started()
        ready.set()

    memo = json.loads(os.getenv("SELFTEST_MEMO") or "{}")
    harness = Harness(bot, name, out, claude=os.getenv("SELFTEST_CLAUDE") == "1", budget=float(os.getenv("SELFTEST_BUDGET") or 0.2))
    harness.memo.update(memo)

    async def run() -> None:
        async with bot.client:
            connecting = asyncio.create_task(bot.client.start(config.TOKEN))
            try:
                await asyncio.wait_for(ready.wait(), 180)
                await harness.setup()
                await phases.PHASES[name](harness)
            finally:
                harness.save()
                await bot.client.close()
                connecting.cancel()

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
