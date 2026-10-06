from types import SimpleNamespace

import pytest

from skills import builtin, registry
from skills.base import ANY

INBOX, ELSEWHERE = 100, 999  # the test settings only name #inbox (and #archive)


@pytest.fixture(scope="module", autouse=True)
def loaded():
    registry.load()


def everything():
    """Every registration of every loaded skill, as (skill name, kind, item)."""
    for entry in registry.catalogue():
        for kind, items in (
            ("keyword", entry.keywords),
            ("reply action", entry.reply_actions),
            ("reaction", entry.reactions),
        ):
            for item in items:
                yield entry.skill.name, kind, item


def names(entries, attribute="keywords"):
    return {item.name for entry in entries for item in getattr(entry, attribute)}


# --- loading ---------------------------------------------------------------
def test_every_skill_loads_without_problems():
    assert registry.problems() == []
    assert [skill.name for skill in registry.loaded_skills()] == ["builtin", "archive", "dev", "lab", "timers"]


def test_every_registration_describes_itself():
    assert registry.missing_descriptions() == []
    for skill, kind, item in everything():
        assert item.description.strip(), f"{skill}: {kind} {item.name} has no description"
        assert item.permission, f"{skill}: {kind} {item.name} has no permission"
        assert item.channels, f"{skill}: {kind} {item.name} doesn't say where it works"


def test_every_registration_has_an_example():
    missing = [f"{skill}: {kind} {item.name}" for skill, kind, item in everything() if not item.examples]
    assert missing == []


def test_destructive_words_must_be_spelled_exactly():
    for term in ("reset", "wipe", "delete", "dev off", "dev reset", "dev clean"):
        kind, _, item = registry.find(term)
        assert item.exact, f"{kind} `{term}` would be matched by a typo"
    for emoji in ("📦", "🗑️"):
        assert registry.find(emoji)[2].destructive


# --- where and for whom ----------------------------------------------------
def test_keywords_default_to_the_inbox_and_say_so():
    _, _, stats = registry.find("stats")
    assert registry.works_in(stats, INBOX)
    assert not registry.works_in(stats, ELSEWHERE)
    assert registry.where(stats) == "#inbox"


def test_any_channel_registrations_work_everywhere():
    for term in ("help", "timer", "dev on", "box", "📦"):
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


def test_the_catalogue_can_show_one_skill(owner):
    entries = registry.catalogue(owner, skill_name="archive")
    assert [entry.skill.name for entry in entries] == ["archive"]
    assert names(entries, "reply_actions") == {"archive", "delete"}
    assert names(entries, "reactions") == {"📦", "🗑️"}


# --- looking things up -----------------------------------------------------
@pytest.mark.parametrize(
    "term, kind, name",
    [
        ("lab", "skill", None),
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


def test_a_skill_name_wins_over_a_word_of_the_same_name():
    assert registry.find("timers")[0] == "skill"


def test_describe_words_shows_arguments_and_aliases():
    assert registry.describe_words(registry.find("stats")[2]) == "stats (also: stat)"
    assert registry.describe_words(registry.find("dev speed")[2]) == "dev speed <n>"


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


def test_help_overview_groups_by_skill(owner):
    text = builtin.build_overview(ctx(owner))
    assert text.startswith("**What I understand here**")
    for heading in ("**Builtin**", "**Archive**", "**Dev**", "**Lab**", "**Timers**"):
        assert heading in text
    assert "• `ping`: check the bot is alive" in text
    assert text.endswith("Anything else goes to Claude. `help <skill or word>` shows details.")


def test_help_overview_summarises_a_skill_with_many_words(owner):
    text = builtin.build_overview(ctx(owner))
    assert "-# `help dev` explains each one" in text
    assert "• `dev on`" not in text


def test_help_overview_only_lists_what_works_in_the_channel(owner):
    text = builtin.build_overview(ctx(owner, ELSEWHERE))
    assert "`ping`" not in text
    assert "`timer <duration> [label]`" in text


def test_help_for_a_skill_lists_every_word_wherever_it_works(owner):
    text = builtin.build_skill_help(ctx(owner, ELSEWHERE), registry.find("dev")[1])
    assert text.startswith("**Dev**\n-# Dev mode for testing")
    assert "• `dev debounce <seconds>`: " in text
    assert "↩️ Reply to a message with:" in text and "`dev inspect`" in text


def test_help_for_a_skill_someone_cannot_use(stranger):
    text = builtin.build_skill_help(ctx(stranger), registry.find("dev")[1])
    assert text == "**Dev** has nothing you can use."


def test_help_for_one_word():
    kind, skill, item = registry.find("reset")
    text = builtin.build_item_help(kind, skill, item)
    assert text.splitlines()[0] == "**`reset`** · Builtin · a word to send on its own"
    assert "Also: `clear`, `clear chat`, `wipe`" in text
    assert "Examples: `reset`, `clear chat`" in text
    assert "Must be spelled exactly (no typo correction)." in text
    assert text.splitlines()[-1] == "Works: #inbox · Needs: `keyword:reset`"


def test_help_for_a_reaction():
    kind, skill, item = registry.find("📦")
    assert builtin.build_item_help(kind, skill, item).startswith(
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
