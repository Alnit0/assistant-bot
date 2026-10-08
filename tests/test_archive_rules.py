from types import SimpleNamespace

import pytest

from core.errors import UserError
from tasks.archive import rules

ARCHIVE, BOT_LOG, INBOX = 200, 300, 100
MB = 1024 * 1024


def message(channel_id=INBOX, content="hello", attachments=(), embeds=()):
    return SimpleNamespace(
        channel=SimpleNamespace(id=channel_id),
        content=content,
        attachments=list(attachments),
        embeds=list(embeds),
    )


def file(size, name="photo.png"):
    return SimpleNamespace(size=size, filename=name)


def embed(kind):
    return SimpleNamespace(type=kind)


# --- archive ---------------------------------------------------------------
def test_an_ordinary_message_can_be_archived():
    rules.check_archivable(message(), ARCHIVE, BOT_LOG)


def test_no_archive_channel_means_nowhere_to_archive_to():
    with pytest.raises(UserError, match="ARCHIVE_CHANNEL_ID"):
        rules.check_archivable(message(), None, BOT_LOG)


def test_a_message_already_in_the_archive_is_refused():
    with pytest.raises(UserError, match="already in the archive"):
        rules.check_archivable(message(channel_id=ARCHIVE), ARCHIVE, BOT_LOG)


def test_bot_log_messages_stay_where_they_are():
    with pytest.raises(UserError, match="bot-log"):
        rules.check_archivable(message(channel_id=BOT_LOG), ARCHIVE, BOT_LOG)


def test_bot_log_is_not_special_when_it_is_not_configured():
    rules.check_archivable(message(channel_id=BOT_LOG), ARCHIVE, None)


def test_a_message_with_nothing_to_copy_is_refused():
    with pytest.raises(UserError, match="nothing in that message"):
        rules.check_archivable(message(content=""), ARCHIVE, BOT_LOG)


@pytest.mark.parametrize(
    "extras",
    [{"attachments": [file(10)]}, {"embeds": [embed("rich")]}],
    ids=["a file", "an embed"],
)
def test_a_message_with_no_text_but_something_else_is_fine(extras):
    rules.check_archivable(message(content="", **extras), ARCHIVE, BOT_LOG)


def test_a_file_too_big_to_re_upload_is_refused_by_name():
    big = message(attachments=[file(1 * MB), file(11 * MB, "film.mp4")])
    with pytest.raises(UserError, match=r"`film\.mp4` is too big .*11\.0 MB"):
        rules.check_archivable(big, ARCHIVE, BOT_LOG)


def test_the_size_limit_is_the_servers_when_given():
    big = message(attachments=[file(11 * MB)])
    rules.check_archivable(big, ARCHIVE, BOT_LOG, size_limit=50 * MB)


def test_a_file_exactly_at_the_limit_is_allowed():
    rules.check_archivable(message(attachments=[file(rules.DEFAULT_SIZE_LIMIT)]), ARCHIVE, BOT_LOG)


# --- delete ----------------------------------------------------------------
def test_an_ordinary_message_can_be_deleted():
    rules.check_deletable(message(), ARCHIVE, BOT_LOG)


def test_an_empty_message_can_still_be_deleted():
    rules.check_deletable(message(content=""), ARCHIVE, BOT_LOG)


def test_archived_copies_are_not_deleted_on_request():
    with pytest.raises(UserError, match="archive stay there"):
        rules.check_deletable(message(channel_id=ARCHIVE), ARCHIVE, BOT_LOG)


def test_bot_log_messages_are_not_deleted_on_request():
    with pytest.raises(UserError, match="bot-log"):
        rules.check_deletable(message(channel_id=BOT_LOG), ARCHIVE, BOT_LOG)


def test_delete_works_without_an_archive_channel():
    rules.check_deletable(message(), None, None)


# --- names, embeds and wording ----------------------------------------------
@pytest.mark.parametrize(
    "name, expected",
    [
        ("Alex", "Alex"),
        ("Discord Fan", "d*scord Fan"),
        ("xXclydeXx", "xXcl*deXx"),
        ("   ", "Unknown"),
        ("", "Unknown"),
        ("a" * 100, "a" * 80),
    ],
)
def test_webhook_safe_names(name, expected):
    assert rules.safe_username(name) == expected


def test_only_the_messages_own_embeds_are_copied():
    rich, preview, also_rich = embed("rich"), embed("link"), embed("rich")
    assert rules.own_embeds([rich, preview, also_rich], 9) == [rich, also_rich]


def test_copied_embeds_leave_room_for_the_note():
    many = [embed("rich") for _ in range(12)]
    assert len(rules.own_embeds(many, 9)) == 9


def test_restoring_swaps_the_archived_note_for_the_restored_one():
    own, archived_note, restored_note = embed("rich"), embed("rich"), embed("rich")
    assert rules.restored_embeds([own, archived_note], restored_note) == [own, restored_note]


def test_restoring_a_copy_with_only_the_note():
    archived_note, restored_note = embed("rich"), embed("rich")
    assert rules.restored_embeds([archived_note], restored_note) == [restored_note]


def test_fallback_text_says_whose_message_it_was():
    assert rules.fallback_text("Alex", "milk, eggs") == "**Alex** wrote:\nmilk, eggs"
    assert rules.fallback_text("Alex", None) == "**Alex** wrote:\n"


def test_fallback_text_fits_in_one_discord_message():
    assert len(rules.fallback_text("Alex", "x" * 5000)) == 2000


def test_delete_preview_is_one_short_line():
    assert rules.delete_preview("first\nsecond") == "first second"
    assert rules.delete_preview(None) == "(no text)"
    assert len(rules.delete_preview("x" * 500)) == 80


def test_the_question_names_the_reason_and_the_action():
    assert rules.confirm_question("pinned", "Archive") == "⚠️ That message is pinned. Archive it anyway?"
    assert rules.confirm_question("marked 📌", "Delete") == "⚠️ That message is marked 📌. Delete it anyway?"
