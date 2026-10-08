import pytest

from core import llm
from core.discord_utils import split_message, truncate


# --- long replies ------------------------------------------------------------
def test_a_short_message_is_one_chunk():
    assert split_message("hello") == ["hello"]


def test_nothing_gives_no_chunks():
    assert split_message("") == []


def test_a_long_message_is_split_at_line_breaks():
    text = "\n".join(["line " + str(number) for number in range(1, 7)])
    chunks = split_message(text, limit=20)
    assert chunks == ["line 1\nline 2", "line 3\nline 4", "line 5\nline 6"]


def test_every_chunk_fits_and_nothing_is_lost():
    text = "\n".join("word " * 30 for _ in range(40))
    chunks = split_message(text)
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_a_line_with_no_breaks_is_cut_at_the_limit():
    chunks = split_message("x" * 45, limit=20)
    assert [len(chunk) for chunk in chunks] == [20, 20, 5]


def test_truncate_leaves_short_text_alone():
    assert truncate("short", 10) == "short"
    assert truncate("x" * 10, 10) == "x" * 10


def test_truncate_marks_what_it_cut():
    assert truncate("x" * 11, 10) == "x" * 9 + "…"
    assert len(truncate("x" * 5000)) == 1000


# --- cost estimates ----------------------------------------------------------
def test_cost_is_worked_out_per_million_tokens():
    assert llm.estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000) == pytest.approx(6.00)
    assert llm.estimate_cost("claude-haiku-4-5", 2000, 500) == pytest.approx(0.0045)


def test_a_dated_model_name_uses_its_familys_price():
    assert llm.estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 0) == pytest.approx(1.00)


def test_an_unknown_model_has_no_estimate():
    assert llm.estimate_cost("some-other-model", 1000, 1000) is None


def test_cost_is_shown_in_us_dollars_or_as_unknown():
    assert llm.format_cost(0.0045) == "US$0.0045"
    assert llm.format_cost(0) == "US$0.0000"
    assert llm.format_cost(None) == "Unknown"


# --- conversation memory -----------------------------------------------------
@pytest.fixture
def no_history(monkeypatch):
    monkeypatch.setattr(llm, "_histories", {})


def test_each_channel_has_its_own_history(no_history):
    llm.history_for(100).append({"role": "user", "content": "inbox"})
    assert llm.history_for(200) == []
    assert llm.history_for(100) == [{"role": "user", "content": "inbox"}]


def test_reset_clears_only_the_channel_it_is_for(no_history):
    llm.history_for(100).append({"role": "user", "content": "inbox"})
    llm.history_for(200).append({"role": "user", "content": "gym"})
    llm.clear_history(100)
    assert llm.history_for(100) == []
    assert len(llm.history_for(200)) == 1


def test_clearing_a_channel_with_no_history_is_fine(no_history):
    llm.clear_history(300)
    assert llm.history_for(300) == []


# --- what Claude is told about itself ----------------------------------------
def test_the_system_prompt_includes_the_capabilities_when_there_are_some():
    assert "- stats: totals" in llm.build_system_prompt("- stats: totals")
    assert "built-in" not in llm.build_system_prompt("")


@pytest.mark.parametrize("capabilities", ["", "- stats: totals"])
def test_claude_is_always_told_it_cannot_act(capabilities):
    prompt = llm.build_system_prompt(capabilities)
    assert "You have no tools yet." in prompt
    assert "cannot run commands or take any action yourself" in prompt
    assert "Never offer to perform an action" in prompt


def test_the_assistant_is_named_from_the_setting(monkeypatch):
    assert llm.build_system_prompt().startswith("You are Hive, "), "the default name"
    monkeypatch.setattr(llm, "ASSISTANT_NAME", "Marvin")
    assert llm.build_system_prompt().startswith("You are Marvin, ")


def test_the_system_prompt_asks_for_uk_spelling_and_short_replies():
    prompt = llm.build_system_prompt()
    assert "UK spelling" in prompt and "short" in prompt


# --- what Claude is told when it has tools ------------------------------------
def test_with_tools_claude_is_told_how_to_use_them():
    prompt = llm.build_system_prompt("- stats: totals", has_tools=True)
    assert "You have no tools yet." not in prompt
    for rule in (
        "decide whether to simply answer, call one or more tools, ask a clarifying question, or propose",
        "call it straight away with propose set to false",
        "ask a short question instead of guessing",
        "unless a tool you called for this very message returned success",
        "Earlier messages are not evidence",
        "Never write a tool call, a tool result or a bracketed note",
        "use that note: answer from it and take ids from it",
        "Never use an earlier message for this",
        "Put every action the user asked for in ONE response",
        "call search_messages to look further back",
        "Never claim or offer to do something you have no tool for",
        "If a tool fails, explain why",
        "at most 5 tool calls",
        "Never guess between them",
    ):
        assert rule in prompt, rule
    assert "- stats: totals" in prompt and "Reactions are theirs alone" in prompt


def test_the_time_is_not_in_the_system_prompt_so_all_of_it_can_be_cached():
    prompt = llm.build_system_prompt("- stats: totals", has_tools=True)
    assert "current date and time" not in prompt
    assert llm.turn_note().splitlines()[1].startswith("The current date and time in Auckland is ")
