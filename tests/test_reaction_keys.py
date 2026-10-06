from core.reactions import Change, final_states, key_for, plan_changes

# Which reaction changes count at all, before working out where they ended up.
INBOX, ELSEWHERE = 100, 999
OWNER_DISCORD, STRANGER_DISCORD = 1, 22
OWNER_ID = 7  # our users.id, deliberately different from the Discord id

REGISTERED = {"📦": {INBOX, ELSEWHERE}, "⭐": {INBOX}}


def works_here(emoji: str, channel_id: int) -> bool:
    return channel_id in REGISTERED.get(emoji, ())


def user_id_for(emoji: str, discord_user_id: int) -> int | None:
    return OWNER_ID if discord_user_id == OWNER_DISCORD else None


def key(emoji="📦", channel_id=INBOX, discord_user_id=OWNER_DISCORD, message_id=10):
    return key_for(Change(message_id, channel_id, emoji, discord_user_id), works_here, user_id_for)


def test_the_owners_registered_reaction_counts():
    assert key() == (10, "📦", OWNER_ID)


def test_the_key_uses_our_user_id_not_the_discord_id():
    assert key()[2] == OWNER_ID != OWNER_DISCORD


def test_an_emoji_nothing_is_registered_for_is_ignored():
    assert key(emoji="👍") is None


def test_a_reaction_in_a_channel_where_it_does_not_work_is_ignored():
    assert key(emoji="⭐", channel_id=INBOX) is not None
    assert key(emoji="⭐", channel_id=ELSEWHERE) is None


def test_someone_who_is_not_allowed_is_ignored():
    assert key(discord_user_id=STRANGER_DISCORD) is None


def test_permission_is_not_even_asked_about_an_unregistered_emoji():
    def must_not_be_asked(emoji, discord_user_id):
        raise AssertionError("no need to look anyone up for an emoji that isn't ours")

    assert key_for(Change(10, INBOX, "👍", OWNER_DISCORD), works_here, must_not_be_asked) is None


def test_only_the_owners_changes_reach_the_decision():
    """The owner adds 📦; a stranger adds and removes theirs. Only the owner's is applied."""
    raw = [
        (Change(10, INBOX, "📦", STRANGER_DISCORD), True),
        (Change(10, INBOX, "📦", OWNER_DISCORD), True),
        (Change(10, INBOX, "📦", STRANGER_DISCORD), False),
        (Change(10, INBOX, "👍", OWNER_DISCORD), True),
    ]
    changes = [
        (found, added)
        for change, added in raw
        if (found := key_for(change, works_here, user_id_for)) is not None
    ]
    to_apply, to_undo = plan_changes(final_states(changes), set())
    assert to_apply == [(10, "📦", OWNER_ID)]
    assert to_undo == []
