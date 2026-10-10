import asyncio
from types import SimpleNamespace

import pytest

from core.errors import UserError
from tasks import builtin, registry
from tasks.base import ANY

INBOX, ELSEWHERE = 100, 999  # the test settings only name #inbox (and #archive)


@pytest.fixture(scope="module", autouse=True)
def loaded():
    registry.load()


def everything():
    """Every registration of every loaded task, as (task name, kind, item)."""
    for entry in registry.catalogue():
        for kind, items in (
            ("keyword", entry.keywords),
            ("reply action", entry.reply_actions),
            ("reaction", entry.reactions),
        ):
            for item in items:
                yield entry.task.name, kind, item


def names(entries, attribute="keywords"):
    return {item.name for entry in entries for item in getattr(entry, attribute)}


# --- loading ---------------------------------------------------------------
def test_every_task_loads_without_problems():
    assert registry.problems() == []
    assert [task.name for task in registry.loaded_tasks()] == [
        "builtin", "archive", "bugs", "dev", "keep", "lab", "pills", "timers"
    ]


def test_every_registration_describes_itself():
    assert registry.missing_descriptions() == []
    for task, kind, item in everything():
        assert item.description.strip(), f"{task}: {kind} {item.name} has no description"
        assert item.permission, f"{task}: {kind} {item.name} has no permission"
        assert item.channels, f"{task}: {kind} {item.name} doesn't say where it works"


def test_every_registration_has_an_example():
    missing = [f"{task}: {kind} {item.name}" for task, kind, item in everything() if not item.examples]
    assert missing == []


def test_destructive_words_must_be_spelled_exactly():
    for term in ("reset", "wipe", "delete", "dev off", "dev reset", "dev clean"):
        kind, _, item = registry.find(term)
        assert item.exact, f"{kind} `{term}` would be matched by a typo"
    for emoji in ("📦", "🗑️"):
        assert registry.find(emoji)[2].destructive


def test_reactions_that_leave_the_message_can_be_undone():
    for entry in registry.catalogue():
        for reaction in entry.reactions:
            # An instant one (🐞) is the stated exception: it is closed another way
            assert reaction.destructive or reaction.instant or reaction.undo is not None, (
                f"{reaction.emoji} can't be undone"
            )


def test_only_the_bug_reaction_skips_the_quiet_period():
    instant = [reaction.emoji for entry in registry.catalogue() for reaction in entry.reactions if reaction.instant]
    assert instant == ["🐞"]


# --- where and for whom ----------------------------------------------------
def test_keywords_default_to_the_inbox_and_say_so():
    _, _, stats = registry.find("stats")
    assert registry.works_in(stats, INBOX)
    assert not registry.works_in(stats, ELSEWHERE)
    assert registry.where(stats) == "#inbox"


def test_any_channel_registrations_work_everywhere():
    for term in ("help", "timer", "dev on", "box", "📦", "📌"):
        item = registry.find(term)[2]
        assert ANY in registry._channel_names(item)
        assert registry.works_in(item, ELSEWHERE)
        assert registry.where(item) == "anywhere"


def test_the_catalogue_is_filtered_by_channel(owner):
    inbox = names(registry.catalogue(owner, INBOX))
    elsewhere = names(registry.catalogue(owner, ELSEWHERE))
    assert {"ping", "stats", "reset", "help", "timer"} <= inbox
    assert {"help", "timer", "dev on"} <= elsewhere
    assert not {"ping", "stats", "reset"} & elsewhere


def test_the_catalogue_is_filtered_by_permission(owner, stranger):
    assert registry.catalogue(owner, INBOX)
    assert registry.catalogue(stranger, INBOX) == []
    assert registry.catalogue(stranger) == []


def test_the_catalogue_can_show_one_task(owner):
    entries = registry.catalogue(owner, task_name="archive")
    assert [entry.task.name for entry in entries] == ["archive"]
    assert names(entries, "reply_actions") == {"archive", "delete"}
    assert names(entries, "reactions") == {"📦", "🗑️"}


# --- looking things up -----------------------------------------------------
@pytest.mark.parametrize(
    "term, kind, name",
    [
        ("lab", "task", None),
        ("stats", "keyword", "stats"),
        ("stat", "keyword", "stats"),  # an alias
        ("STATS", "keyword", "stats"),
        ("statss", "keyword", "stats"),  # a forgiven typo
        ("clear chat", "keyword", "reset"),
        ("pomo stats", "keyword", "pomo stats"),
        ("dev fire next", "keyword", "dev fire next"),
        ("box", "reply action", "archive"),
        ("file away", "reply action", "archive"),
        ("dev inspect", "reply action", "dev inspect"),
        ("📦", "reaction", "📦"),
        ("📌", "reaction", "📌"),
        ("🗑", "reaction", "🗑️"),  # without the invisible emoji-style character
    ],
)
def test_find(term, kind, name):
    found = registry.find(term)
    assert found is not None, term
    assert found[0] == kind
    assert (found[2].name if found[2] is not None else None) == name


@pytest.mark.parametrize("term", ["nonsense", "me write an email", "resett", "delet", "👍"])
def test_find_knows_what_it_does_not_know(term):
    assert registry.find(term) is None


def test_a_task_name_wins_over_a_word_of_the_same_name():
    assert registry.find("timers")[0] == "task"


def test_describe_words_shows_arguments_and_aliases():
    assert registry.describe_words(registry.find("stats")[2]) == "stats (also: stat)"
    assert registry.describe_words(registry.find("dev speed")[2]) == "dev speed <n>"


# --- replies in ordinary words -----------------------------------------------
@pytest.mark.parametrize(
    "text, name",
    [
        ("pin", "pin"),
        ("pin this", "pin"),
        ("pin me", "pin"),
        ("Please archive it", "archive"),
        ("delete this", "delete"),
        ("unpin that one", "unpin"),
    ],
)
def test_a_reply_may_carry_filler_words(text, name):
    assert registry._reply_router.match(text, fillers=True).entry[1].name == name


def test_filler_words_do_not_loosen_anything_else():
    assert registry._reply_router.match("delet this", fillers=True) is None, "delete is still exact"
    assert registry._reply_router.match("pin this to the wall", fillers=True) is None
    assert registry._keyword_router.match("ping me") is None, "typed words are unchanged"


# --- refusing at once --------------------------------------------------------
ARCHIVE = 200  # the test settings' archive channel
BUGS = 300  # and their #bugs forum


def message_in(channel_id: int):
    return SimpleNamespace(
        channel=SimpleNamespace(id=channel_id), content="text", attachments=[], embeds=[], guild=None
    )


def test_archive_and_delete_can_be_checked_before_anything_is_done():
    # "box" because `archive` on its own finds the task of that name
    for term in ("box", "delete", "📦", "🗑️"):
        item = registry.find(term)[2]
        assert item.validate is not None, term
        item.validate(message_in(ELSEWHERE))
        with pytest.raises(UserError):
            item.validate(message_in(ARCHIVE))


@pytest.fixture
def reactions_watched(owner, monkeypatch):
    """Stand-ins around registry.reaction_changed: what was debounced, refused and marked."""
    seen = SimpleNamespace(debounced=[], refused=[], marks=[], message=message_in(ARCHIVE))

    async def user(discord_id):
        return owner

    async def fetch(channel_id, message_id):
        return seen.message

    async def refuse(task, reaction, payload, user, reason):
        seen.refused.append((reaction.emoji, reason))

    async def mark(channel_id, message_id, emoji, add=True):
        seen.marks.append((emoji, add))

    monkeypatch.setattr(registry, "_reaction_debouncer", SimpleNamespace(trigger=seen.debounced.append))
    monkeypatch.setattr(registry, "get_user_by_discord_id", user)
    monkeypatch.setattr(registry, "_fetch_message", fetch)
    monkeypatch.setattr(registry, "_refuse_reaction", refuse)
    monkeypatch.setattr(registry, "_mark", mark)
    monkeypatch.setattr(registry, "_refused", set())
    return seen


def reaction(emoji: str, user_id: int = 1):
    return SimpleNamespace(emoji=emoji, channel_id=ARCHIVE, message_id=5, user_id=user_id)


def test_an_invalid_reaction_is_refused_at_once_and_never_debounced(reactions_watched):
    asyncio.run(registry.reaction_changed(reaction("📦"), True))
    assert reactions_watched.refused == [("📦", "That message is already in the archive.")]
    assert reactions_watched.debounced == []


def test_taking_a_refused_reaction_off_clears_its_warning(reactions_watched):
    payload = reaction("📦")
    asyncio.run(registry.reaction_changed(payload, True))
    asyncio.run(registry.reaction_changed(payload, False))
    assert reactions_watched.marks == [("⚠️", False)]
    assert reactions_watched.debounced == [], "nothing was pending, so there is nothing to cancel"


def test_a_valid_reaction_waits_out_the_quiet_period(reactions_watched):
    reactions_watched.message = message_in(ELSEWHERE)
    added, removed = reaction("📦"), reaction("📦")
    asyncio.run(registry.reaction_changed(added, True))
    asyncio.run(registry.reaction_changed(removed, False))
    assert reactions_watched.refused == []
    assert reactions_watched.debounced == [(added, True), (removed, False)]


def test_a_reaction_with_no_check_goes_straight_to_the_debouncer(reactions_watched):
    payload = reaction("📌")
    asyncio.run(registry.reaction_changed(payload, True))
    assert reactions_watched.debounced == [(payload, True)]


def test_an_instant_reaction_runs_at_once_and_is_never_debounced(reactions_watched, monkeypatch):
    applied = []

    async def apply(key, payload, user):
        applied.append(key)

    monkeypatch.setattr(registry, "_apply_reaction", apply)
    reactions_watched.message = message_in(ELSEWHERE)
    payload = reaction("🐞")
    asyncio.run(registry.reaction_changed(payload, True))
    assert applied == [(5, "🐞", 1)]
    assert reactions_watched.debounced == []


def test_taking_an_instant_reaction_away_does_nothing(reactions_watched, monkeypatch):
    applied = []

    async def apply(key, payload, user):
        applied.append(key)

    monkeypatch.setattr(registry, "_apply_reaction", apply)
    asyncio.run(registry.reaction_changed(reaction("🐞"), False))
    assert applied == [] and reactions_watched.debounced == [] and reactions_watched.marks == []


def test_an_instant_reaction_from_someone_else_does_nothing(reactions_watched, stranger, monkeypatch):
    applied = []

    async def apply(key, payload, user):
        applied.append(key)

    async def user(discord_id):
        return stranger

    monkeypatch.setattr(registry, "_apply_reaction", apply)
    monkeypatch.setattr(registry, "get_user_by_discord_id", user)
    reactions_watched.message = message_in(ELSEWHERE)
    asyncio.run(registry.reaction_changed(reaction("🐞", user_id=22), True))
    assert applied == []


def test_a_reaction_inside_a_bugs_post_is_refused_at_once(reactions_watched):
    reactions_watched.message = SimpleNamespace(channel=SimpleNamespace(id=7, parent_id=BUGS))
    asyncio.run(registry.reaction_changed(reaction("🐞"), True))
    assert reactions_watched.refused == [("🐞", "That is already in a bug's post: write the note there instead.")]


# --- a message taken because of where it was sent ------------------------------
class ClaimCtx:
    def __init__(self, user, parent_channel_id):
        self.user, self.parent_channel_id = user, parent_channel_id
        self.text, self.message_id, self.channel_id = "it said 5m, not 50m", 9, 7
        self.failed, self.errors = False, []

    async def mark_failed(self):
        self.failed = True

    async def log_error(self, title, details, text=None):
        self.errors.append((title, details))


@pytest.fixture
def claims_logged(monkeypatch):
    rows = []

    async def received(content, kind, *ids, **more):
        rows.append([kind, None])
        return len(rows) - 1

    async def result(row_id, **fields):
        rows[row_id][1] = fields.get("status")

    monkeypatch.setattr(registry, "log_received", received)
    monkeypatch.setattr(registry, "log_result", result)
    return rows


def test_a_message_in_a_bugs_post_is_claimed_before_claude(owner, claims_logged, monkeypatch):
    from tasks import bugs

    saved = []

    async def save(ctx):
        saved.append(ctx.text)
        return "note saved for B1"

    monkeypatch.setattr(bugs, "save_note", save)
    assert asyncio.run(registry.dispatch_claimed(ClaimCtx(owner, BUGS))) is True
    assert saved == ["it said 5m, not 50m"] and claims_logged == [["claimed", "ok"]]


def test_a_message_anywhere_else_is_nobodys(owner, claims_logged):
    assert asyncio.run(registry.dispatch_claimed(ClaimCtx(owner, None))) is False
    assert asyncio.run(registry.dispatch_claimed(ClaimCtx(owner, ELSEWHERE))) is False
    assert claims_logged == []


def test_a_claimed_message_from_someone_else_is_dropped(stranger, claims_logged, monkeypatch):
    from tasks import bugs

    async def save(ctx):
        raise AssertionError("a stranger's message must not be saved")

    monkeypatch.setattr(bugs, "save_note", save)
    assert asyncio.run(registry.dispatch_claimed(ClaimCtx(stranger, BUGS))) is True
    assert claims_logged == [["claimed", "denied"]]


def test_a_claimed_message_that_fails_is_flagged(owner, claims_logged, monkeypatch):
    from tasks import bugs

    async def save(ctx):
        raise UserError("no")

    monkeypatch.setattr(bugs, "save_note", save)
    ctx = ClaimCtx(owner, BUGS)
    assert asyncio.run(registry.dispatch_claimed(ctx)) is True
    assert ctx.failed and ctx.errors == [("Message for bugs failed", "no")]
    assert claims_logged == [["claimed", "error"]]


def test_an_unregistered_emoji_is_ignored(reactions_watched):
    asyncio.run(registry.reaction_changed(reaction("👍"), True))
    assert reactions_watched.debounced == [] and reactions_watched.refused == []


def test_someone_who_is_not_allowed_is_not_told_why(reactions_watched, stranger, monkeypatch):
    async def user(discord_id):
        return stranger

    monkeypatch.setattr(registry, "get_user_by_discord_id", user)
    payload = reaction("📦", user_id=22)
    asyncio.run(registry.reaction_changed(payload, True))
    assert reactions_watched.refused == [], "ignored without comment, as before"
    assert reactions_watched.debounced == [(payload, True)]


# --- what Claude is told ---------------------------------------------------
def test_claude_is_told_what_help_shows(owner):
    text = registry.capabilities_text(owner, INBOX)
    assert "Words to send as a message on their own:" in text
    assert "- stats (also: stat): all-time usage totals" in text
    assert "Words to send as a reply to a message" in text
    assert "Reactions to add to a message:" in text
    for entry in registry.catalogue(owner, INBOX):
        for keyword in entry.keywords:
            assert f"- {registry.describe_words(keyword)}: " in text


def test_claude_is_told_nothing_for_someone_who_may_do_nothing(stranger):
    assert registry.capabilities_text(stranger, INBOX) == ""


# --- help ------------------------------------------------------------------
def ctx(user, channel_id=INBOX):
    return SimpleNamespace(user=user, channel_id=channel_id)


def test_help_overview_groups_by_task(owner):
    text = builtin.build_overview(ctx(owner))
    assert text.startswith("**What I understand here**")
    for heading in ("**Builtin**", "**Archive**", "**Bugs**", "**Dev**", "**Keep**", "**Lab**", "**Pills**", "**Timers**"):
        assert heading in text
    assert "• `ping`: check the bot is alive" in text
    assert text.endswith("Anything else goes to Claude. `help <task or word>` shows details.")


def test_help_overview_summarises_a_task_with_many_words(owner):
    text = builtin.build_overview(ctx(owner))
    assert "-# `help dev` explains each one" in text
    assert "• `dev on`" not in text


def test_help_overview_only_lists_what_works_in_the_channel(owner):
    text = builtin.build_overview(ctx(owner, ELSEWHERE))
    assert "`ping`" not in text
    assert "`timer <duration> [label]`" in text


def test_help_for_a_task_lists_every_word_wherever_it_works(owner):
    text = builtin.build_task_help(ctx(owner, ELSEWHERE), registry.find("dev")[1])
    assert text.startswith("**Dev**\n-# Dev mode for testing")
    assert "• `dev debounce <seconds>`: " in text
    assert "↩️ Reply to a message with:" in text and "`dev inspect`" in text


def test_help_for_a_task_someone_cannot_use(stranger):
    text = builtin.build_task_help(ctx(stranger), registry.find("dev")[1])
    assert text == "**Dev** has nothing you can use."


def test_help_for_one_word():
    kind, task, item = registry.find("reset")
    text = builtin.build_item_help(kind, task, item)
    assert text.splitlines()[0] == "**`reset`** · Builtin · a word to send on its own"
    assert "Also: `clear`, `clear chat`, `wipe`" in text
    assert "Examples: `reset`, `clear chat`" in text
    assert "Must be spelled exactly (no typo correction)." in text
    assert text.splitlines()[-1] == "Works: #inbox · Needs: `keyword:reset`"


def test_help_for_a_reaction():
    kind, task, item = registry.find("📦")
    assert builtin.build_item_help(kind, task, item).startswith(
        "**📦** · Archive · a reaction to add to a message"
    )


@pytest.mark.parametrize(
    "words, is_help",
    [
        ([], True),
        (["stats"], True),
        (["lab"], True),
        (["clear", "chat"], True),
        (["me", "write", "an", "email"], False),
        (["please"], False),
    ],
)
def test_help_with_other_words_is_a_message_for_claude(words, is_help):
    assert builtin._help_accepts(words) is is_help


# --- words added after QA ----------------------------------------------------
@pytest.mark.parametrize("typed, args", [("dev mode on", ["on"]), ("Dev mode off", ["off"])])
def test_dev_mode_on_and_off_are_typed_words(typed, args):
    match = registry._keyword_router.match(typed)
    keyword = match.entry[1]
    assert keyword.name == "dev mode" and match.args == args and keyword.accepts(match.args)
    assert not keyword.exact


@pytest.mark.parametrize("typed", ["dev mode", "dev mode please", "dev mode on now"])
def test_dev_mode_with_anything_else_is_not_the_switch(typed):
    match = registry._keyword_router.match(typed)
    assert match is None or match.entry[1].name != "dev mode" or not match.entry[1].accepts(match.args)


def test_unpause_is_another_word_for_resume():
    assert registry._reply_router.match("unpause").entry[1].name == "resume"


# --- which tasks are loaded: ENABLED_TASKS, or the old ENABLED_SKILLS ------------
@pytest.mark.parametrize(
    "new, old, expected",
    [
        ("builtin, Timers", "", ["builtin", "timers"]),
        ("", "builtin,keep", ["builtin", "keep"]),  # an .env from before the rename still works
        (None, "keep", ["keep"]),
        ("timers", "keep", ["timers"]),  # the new name wins
        ("", "", None),  # neither: load them all
        (None, None, None),
        (" , ", "", None),
    ],
)
def test_the_old_setting_is_read_when_the_new_one_is_empty(new, old, expected):
    from core import config

    assert config.names_in(new, old) == expected


# --- the ambiguity rule: shortcuts carry their task's name ----------------------
def test_no_typed_shortcut_is_a_bare_generic_verb():
    from core.router import GENERIC_VERBS, is_generic

    for task, kind, item in everything():
        if kind == "keyword":
            for word in item.words:
                assert not is_generic(word), f"{task}: `{word}` could be any task's; put the task's name in it"
    assert {"add", "edit", "remove", "delete", "pause", "resume", "list"} <= GENERIC_VERBS
    assert is_generic("Add") and is_generic(" add ") and not is_generic("pill add") and not is_generic("timer")


@pytest.mark.parametrize("typed", ["add milk", "add vitamin D", "remove iron", "pause", "list", "edit the evening pill"])
def test_a_bare_generic_verb_matches_no_shortcut(typed):
    assert registry._keyword_router.match(typed) is None, "it goes to Claude, which works out the task or asks"


def test_two_tasks_that_both_want_add_can_claim_it_only_with_their_name(monkeypatch):
    from core.router import Router
    from tasks.base import Keyword, Task

    async def handler(ctx):
        return None

    class Pills(Task):
        name = "pillbox"

    class Shopping(Task):
        name = "shopping"

    router = Router()
    monkeypatch.setattr(registry, "_problems", [])
    for task, phrase in ((Pills(), "pill add"), (Shopping(), "shop add")):
        # Each tries the bare verb as well as its own namespaced phrase
        keyword = Keyword(["add", phrase], "add an item", handler, examples=[phrase], takes_args=True)
        registry._register_words(router, task, "keyword", keyword)

    assert router.match("add milk") is None, "the bare verb belongs to neither"
    assert router.match("pill add milk").entry[0].name == "pillbox"
    assert router.match("shop add milk").entry[0].name == "shopping"
    assert registry._problems == [
        "pillbox: keyword `add` is a bare generic verb; put the task's name in it",
        "shopping: keyword `add` is a bare generic verb; put the task's name in it",
    ]
