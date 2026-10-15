from core import repeats
from core.errors import UserError
from core.users import User
from tasks.bugs import capture, listing, posts, rules, store

# ---------------------------------------------------------------------------
# Logging a bug and saving a note, for every way in (🐞, the word, a reply,
# plain words). Nothing is said to be logged or saved until it has been read
# back from the database. The Discord work is in posts.py.
# ---------------------------------------------------------------------------
NOT_LOGGED = "That didn't save: the bug was not logged. Report it again."
NOTE_NOT_SAVED = "That didn't save: your note was not kept. Write it again."


async def file_report(
    user: User, channel_id: int, target: rules.Snapshot, before: list[rules.Snapshot], source: str,
    exclude_message_id: int | None = None,
) -> str:
    """Log a bug against a message and open its post. Returns the line for the
    channel. A message that already has an open bug is pointed to, not logged twice."""
    # The same message again: what that means is the task's declaration (core/repeats.py)
    repeat = repeats.decide(rules.ON_REPEAT, await store.open_for(user.id, channel_id, target.message_id))
    if repeat.kind == repeats.EXISTING:
        return rules.logged_text(repeat.there.id, repeat.there.post_url, existing=True)
    # Before anything is recorded: is there somewhere to put the post?
    posts.forum()
    report = await capture.build(
        source=source, channel_id=channel_id, target=target, preceding=before, exclude_message_id=exclude_message_id
    )
    again = await reported_again(user, report)
    if again is not None:
        return again
    number = await store.add(user.id, report)
    thread_id, url = await posts.create_post(number, report)
    await store.set_post(number, thread_id, url)
    # "Logged as B4" is said of the bug as it is in the database, with the post it has there
    saved = await store.get(number)
    if saved is None or saved.post_url != url:
        raise UserError(NOT_LOGGED)
    listing.changed(user.id)
    return rules.logged_text(saved.id, saved.post_url)


async def reported_again(user: User, report: rules.Report) -> str | None:
    """A bug with a fix shipped, reported again with one of my own messages word for word: that bug
    stays open (no longer closing by itself) with this report as a note, and no new bug. None otherwise."""
    for item in await store.shipped(user.id):
        if rules.said_again(item.report, report):
            await store.unship(item.id)
            await store.add_note(item.id, user.id, rules.OWNER, f"Reported again: {report.target.url or 'the same words'}")
            await posts.bring_up_to_date(await store.get(item.id), rules.kept_open_text(item.id, "you reported it again"))
            listing.changed(user.id)
            return f"🐞 That looks like [{rules.bug_id(item.id)}]({item.post_url}) again: it stays open, with this as a note"
    return None


async def add_note(item_id: int, user_id: int | None, content: str, message_id: int | None) -> bool:
    """Keep a note with a bug and bring its post's card up to date. True only if
    the note is there when read back."""
    before = len(await store.notes(item_id))
    await store.add_note(item_id, user_id, rules.OWNER, content, message_id)
    kept = await store.notes(item_id)
    saved = len(kept) == before + 1 and kept[-1].content == content
    if saved:
        # The count on the post's opening card, in place
        await posts.refresh_card(await store.get(item_id))
        listing.changed(user_id)
    return saved
