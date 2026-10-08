import asyncio
from datetime import datetime, timezone

import pytest

from tasks.archive import store

POSTED = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)
INBOX, ARCHIVE = 100, 200
ORIGINAL, COPY, BUTTON = 5001, 6001, 6002


@pytest.fixture
def archive_db(make_db):
    make_db({"archive": store.MIGRATIONS})


def add(original_message_id=ORIGINAL) -> int:
    return asyncio.run(
        store.add(1, INBOX, original_message_id, ARCHIVE, "Alex", "https://example.com/a.png", POSTED)
    )


def test_a_record_remembers_where_the_message_came_from(archive_db):
    item_id = add()
    asyncio.run(store.set_copy(item_id, COPY, None))

    item = asyncio.run(store.get(item_id))
    assert (item.original_channel_id, item.original_message_id) == (INBOX, ORIGINAL)
    assert (item.archive_channel_id, item.archive_message_id, item.button_message_id) == (ARCHIVE, COPY, None)
    assert (item.author_name, item.author_avatar_url) == ("Alex", "https://example.com/a.png")
    assert item.original_created_at == POSTED
    assert item.user_id == 1


def test_a_separate_restore_button_message_is_remembered(archive_db):
    item_id = add()
    asyncio.run(store.set_copy(item_id, COPY, BUTTON))
    assert asyncio.run(store.get(item_id)).button_message_id == BUTTON


def test_a_restored_item_cannot_be_restored_twice(archive_db):
    item_id = add()
    asyncio.run(store.set_copy(item_id, COPY, None))
    asyncio.run(store.mark_restored(item_id))
    assert asyncio.run(store.get(item_id)) is None


def test_a_discarded_record_is_gone(archive_db):
    item_id = add()
    asyncio.run(store.discard(item_id))
    assert asyncio.run(store.get(item_id)) is None
    assert asyncio.run(store.describe_record(ORIGINAL)) is None


def test_an_unknown_item_is_none(archive_db):
    assert asyncio.run(store.get(999)) is None


@pytest.mark.parametrize("message_id", [ORIGINAL, COPY, BUTTON], ids=["original", "copy", "button"])
def test_a_record_is_found_by_any_of_its_messages(archive_db, message_id):
    item_id = add()
    asyncio.run(store.set_copy(item_id, COPY, BUTTON))
    text = asyncio.run(store.describe_record(message_id))
    assert text.startswith(f"item {item_id}: from <#{INBOX}> to <#{ARCHIVE}>, archived <t:")
    assert "restored" not in text


def test_the_description_says_when_it_was_restored(archive_db):
    item_id = add()
    asyncio.run(store.set_copy(item_id, COPY, None))
    asyncio.run(store.mark_restored(item_id))
    assert ", restored <t:" in asyncio.run(store.describe_record(COPY))


def test_a_message_that_was_never_archived_has_no_record(archive_db):
    add()
    assert asyncio.run(store.describe_record(424242)) is None


def test_the_newest_record_wins_for_a_message_archived_twice(archive_db):
    add()
    second = add()
    assert asyncio.run(store.describe_record(ORIGINAL)).startswith(f"item {second}:")
