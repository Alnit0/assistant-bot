import logging
from datetime import datetime, timezone

from core import config
from core.errors import UserError
from core.users import get_user_by_discord_id
from tasks.bugs import capture, listing, posts, rules, store

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Bugs the bot files about itself (asked for by core/health.py): a job that
# did not work, its own memory use. One bug for each kind of problem, known
# by its key in words ("the nightly backup job"): while that bug is open, the
# next time is a note on it, never a second bug. It is an ordinary bug in
# every other way: its post in the forum, mine to close with Fixed or Won't
# fix. The bot never closes it.
# ---------------------------------------------------------------------------


async def _open(key: str) -> store.Item | None:
    owner = await get_user_by_discord_id(config.OWNER_ID)
    if owner is None:
        return None
    return next((item for item in await store.open_items(owner.id) if item.report.source == rules.SYSTEM and item.report.channel == key), None)


async def find(key: str) -> str:
    """The id of the open bug for this kind of problem, or ""."""
    item = await _open(key)
    return rules.bug_id(item.id) if item is not None else ""


async def file(key: str, summary: str, details: str) -> str:
    """File a bug for this kind of problem, or add a note to the one that is open. Returns its id."""
    when = datetime.now(timezone.utc).isoformat()
    item = await _open(key)
    if item is not None:
        await store.add_note(item.id, item.user_id, rules.THE_BOT, f"Again: {summary}. {details}", None)
        await posts.refresh_card(await store.get(item.id))
        listing.changed(item.user_id)
        log.info("Bug %s (%s): it happened again, noted", rules.bug_id(item.id), key)
        return rules.bug_id(item.id)
    owner = await get_user_by_discord_id(config.OWNER_ID)
    if owner is None:
        return ""
    report = rules.Report(
        source=rules.SYSTEM, channel_id=0, channel=key, target=rules.Snapshot(0, rules.THE_BOT, f"{summary}\n{details}", when),
        commit=await capture.git_commit(), reported_at=when,
    )
    number = await store.add(owner.id, report)
    try:
        thread_id, url = await posts.create_post(number, report)
        await store.set_post(number, thread_id, url)
    except UserError as error:
        # The bug is on record all the same; its post can't be made (no forum, no permission)
        log.warning("Bug %s (%s) has no post: %s", rules.bug_id(number), key, error)
    listing.changed(owner.id)
    log.info("Bug %s filed by the bot itself: %s", rules.bug_id(number), key)
    return rules.bug_id(number)
