"""The typed shortcut "took <pill>" (tasks/pills/shortcut.py), the dev bot's own settings file, and keep without discord.py."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import config, design, llm, occurrences
from tasks import registry
from tasks.pills import shortcut
from tests.test_pills_reminders import EVENING, HUB, INBOX, PILL_A, add, at, log, run, states, world  # noqa: F401


class Ctx:
    def __init__(self, world, text):
        self.user, self.channel_id, self.message_id, self.text = world.owner, INBOX, 4321, text
        self.args = text.split()[1:]
        self.said, self.noted, self.world = [], [], world

    async def reply(self, text):
        self.said.append(text)
        self.world.next_id += 1
        return SimpleNamespace(id=self.world.next_id)

    def shown(self, text):
        self.noted.append(text)


def claims(world, text):
    ctx = Ctx(world, text)
    return run(shortcut.claims(ctx, ctx.args))


# --- when it is the shortcut -----------------------------------------------------------------------------------
def test_only_the_exact_name_of_one_of_my_pills_with_nothing_else_is_the_shortcut(world):
    add(world, EVENING, {"name": "Zinc"}, {"name": "Zinc forte"})
    assert claims(world, "took zinc") and claims(world, "took ZINC") and claims(world, "took  Evening   pill")
    assert claims(world, "took zinc forte")
    for said in ("took", "took my zinc", "took zinc at 9", "took zinc and evening pill", "took zin", "took forte", "took iron", "took it"):
        assert not claims(world, said), f"{said!r} is read as it always was"


def test_with_nothing_left_to_take_of_it_today_it_is_not_the_shortcut(world):
    add(world, {"name": "Zinc"})
    log(world, {"pill": "zinc", "did": "taken"})
    assert not claims(world, "took zinc"), "what to say about a pill already taken is the task's plain-words code's"


def test_it_is_a_typed_word_of_pills_exact_and_the_only_bare_verb():
    registry.load()
    kind, task, item = registry.find("took")
    assert (kind, task.name, item.takes_args, item.exact, item.keep_command) == ("keyword", "pills", True, True, True)
    assert item.claims is shortcut.claims
    assert registry._keyword_router.match("took zinc") is not None, "the registry asks `claims` before it is run"
    assert registry._keyword_router.match("tok zinc") is None, "never by a typo"
    assert registry._keyword_router.match("add milk") is None and registry._keyword_router.match("take zinc") is None


def test_a_message_the_shortcut_does_not_claim_is_not_run_as_one(world, monkeypatch):
    registry.load()
    add(world, {"name": "Zinc"})
    ran = []

    async def run_keyword(ctx, **how):
        ran.append(how["name"])
        return "ok", ""

    monkeypatch.setattr(registry, "_run", run_keyword)
    monkeypatch.setattr(registry, "works_in", lambda item, channel_id: True)
    assert run(registry.dispatch_keyword(Ctx(world, "took my zinc"))) is False and ran == [], "on to the router"
    assert run(registry.dispatch_keyword(Ctx(world, "took zinc"))) is True and ran == ["took"]


# --- what it does ----------------------------------------------------------------------------------------------
def test_it_ticks_the_next_dose_off_now_as_saying_it_would_and_asks_claude_nothing(world, monkeypatch):
    async def never(*_, **__):
        raise AssertionError("no request to Claude is made for the shortcut")

    monkeypatch.setattr(llm, "call_tool", never)
    monkeypatch.setattr(llm, "ask_claude", never)
    add(world, EVENING)
    at(world, 20, 5)
    ctx = Ctx(world, "took Evening pill")
    said = run(shortcut.took(ctx))
    assert said == ctx.said[0] and said.startswith("✅ **Evening pill** · taken 8:05 pm")
    assert states(world)[("Evening pill", 1)] == occurrences.DONE
    assert llm.answering_task(INBOX) == "pills", "a short message that follows is about this"
    # The same words as saying it gives
    add(world, {"name": "Other"})
    assert log(world, {"pill": "other", "did": "taken"}).startswith("✅ **Other** · taken 8:05 pm")


def test_the_line_it_says_is_that_pill_s_so_a_reply_to_it_means_that_dose(world):
    from tasks.pills import store

    add(world, EVENING)
    at(world, 20, 5)
    ctx = Ctx(world, "took evening pill")
    run(shortcut.took(ctx))
    about = run(world.request().db.run(store.db_line, world.next_id))
    pill = run(store.pills(world.owner.id))[0]
    assert [pill_id for pill_id, _ in about] == [pill.id], "recorded as a line about that pill"


def test_too_soon_is_asked_first_on_the_card_and_nothing_is_logged(world):
    add(world, PILL_A)
    at(world, 8, 0)
    run(shortcut.took(Ctx(world, "took pill a")))
    at(world, 9, 0)
    sent = len(world.sent)
    ctx = Ctx(world, "took pill a")
    assert run(shortcut.took(ctx)) == "asked first on a card" and ctx.said == [] and ctx.noted == ["asked first on a card"]
    assert states(world)[("Pill A", 2)] == occurrences.PENDING
    asked = world.sent[sent].card
    assert "Log it anyway?" in asked.text and [button.label for button in asked.rows[0]] == ["Log it", "Cancel"]
    assert asked.layout[0].status == design.RISKY


# --- the dev bot's own settings ----------------------------------------------------------------------------------
def test_with_dev_a_settings_file_of_its_own_comes_first_and_without_one_nothing_changes(tmp_path):
    (tmp_path / ".env").write_text("DISCORD_TOKEN=live", encoding="utf-8")
    assert config.env_files(True, tmp_path) == [tmp_path / ".env"], "no .env.dev: --dev is the live bot's account, as before"
    (tmp_path / ".env.dev").write_text("DISCORD_TOKEN=dev", encoding="utf-8")
    assert config.env_files(True, tmp_path) == [tmp_path / ".env.dev", tmp_path / ".env"], "the first to set a name keeps it"
    assert config.env_files(False, tmp_path) == [tmp_path / ".env"], "the live bot never reads .env.dev"


def test_the_dev_settings_file_is_never_committed_and_has_an_example():
    ignored = (config.BASE_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env.dev" in ignored and ".env" in ignored
    example = (config.BASE_DIR / ".env.dev.example").read_text(encoding="utf-8")
    assert "DISCORD_TOKEN=\n" in example.replace("\r\n", "\n") and "INBOX_CHANNEL_ID=" in example
    assert not any(line.split("=", 1)[1].strip() for line in example.splitlines() if "=" in line and not line.startswith("#")), "placeholders only"


# --- keep --------------------------------------------------------------------------------------------------------
def test_keep_uses_no_discord_py():
    source = Path(config.BASE_DIR / "tasks" / "keep" / "__init__.py").read_text(encoding="utf-8")
    assert "import discord" not in source and "discord." not in source.replace("discord.py", "")
