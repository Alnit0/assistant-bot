from datetime import datetime, timedelta, timezone

import pytest

from core import devmode, tools
from core.tools import ERROR, MANY, ONE, REPLY, ToolSpec
from tasks import registry
from tasks.base import Param
from tasks.timers.durations import split_duration
from tasks.timers.pomodoro import parse_session

INBOX, ELSEWHERE = 100, 999
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def loaded():
    registry.load()


def by_name(specs) -> dict[str, ToolSpec]:
    return {spec.name: spec for spec in specs}


# --- names -------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind, name, expected",
    [
        (tools.KEYWORD, "timer", "timer"),
        (tools.KEYWORD, "pomo stats", "pomo_stats"),
        (tools.KEYWORD, "dev fire next", "dev_fire_next"),
        (tools.REPLY_ACTION, "archive", "reply_archive"),
        (tools.REPLY_ACTION, "dev inspect", "reply_dev_inspect"),
    ],
)
def test_tool_names_are_what_the_api_accepts(kind, name, expected):
    assert tools.tool_name(kind, name) == expected


def test_every_tool_name_is_valid_and_unique(owner, dev_off):
    devmode.enable()
    names = [spec.name for spec in registry.tools_for(owner, INBOX)]
    assert len(names) == len(set(names))
    for name in names:
        assert name.replace("_", "").isalnum() and len(name) <= 64, name


# --- schemas -----------------------------------------------------------------
DURATION = Param("duration", "How long, e.g. 25m.")
LABEL = Param("label", "A name.", required=False)
MODE = Param("mode", "auto or manual.", choices=("auto", "manual"), required=False)


def test_a_schema_requires_everything_and_allows_nothing_else():
    schema = tools.build_schema([DURATION, LABEL], propose=True)
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert list(schema["properties"]) == ["duration", "label", "propose"]
    assert schema["required"] == ["duration", "label", "propose"]
    assert schema["properties"]["propose"]["type"] == "boolean"


def test_an_argument_that_may_be_left_out_is_a_string_that_may_be_empty():
    schema = tools.build_schema([LABEL, MODE])
    assert schema["properties"]["label"] == {
        "type": "string",
        "description": "A name. Use an empty string to leave it out.",
    }
    assert schema["properties"]["mode"]["enum"] == ["auto", "manual", ""]
    assert tools.build_schema([Param("state", "on or off.", choices=("on", "off"))])["properties"]["state"]["enum"] == ["on", "off"]


def test_no_schema_uses_what_strict_mode_cannot_take(owner, dev_off):
    """No unions, no optional properties, no numeric or length limits, in any generated tool."""
    devmode.enable()
    for spec in registry.tools_for(owner, INBOX):
        schema = spec.schema
        assert schema["additionalProperties"] is False, spec.name
        assert schema["required"] == list(schema["properties"]), spec.name
        for rules in schema["properties"].values():
            assert isinstance(rules["type"], str), spec.name
            assert not {"anyOf", "minimum", "maximum", "minLength", "maxLength", "minItems"} & set(rules), spec.name


def test_message_actions_take_targets_and_destructive_ones_cannot_be_proposed(owner):
    specs = by_name(registry.tools_for(owner, INBOX))
    assert tools.TARGETS in specs["reply_archive"].schema["properties"]
    assert tools.TARGETS not in specs["timer"].schema["properties"]
    assert tools.PROPOSE in specs["timer"].schema["properties"]
    for name in ("reset", "reply_delete"):
        assert specs[name].destructive
        assert tools.PROPOSE not in specs[name].schema["properties"], "these always ask with buttons"
        assert "confirm with buttons" in specs[name].description


# --- checking what Claude sends ----------------------------------------------
SCHEMA = tools.build_schema([DURATION, MODE], propose=True, targets=True)
GOOD = {"duration": "5m", "mode": "", "targets": ["m1"], "propose": False}


def test_a_fitting_input_has_no_problems():
    assert tools.validate(SCHEMA, GOOD) == []


@pytest.mark.parametrize(
    "change, problem",
    [
        ({"duration": 5}, "`duration` must be a string"),
        ({"mode": "sometimes"}, "`mode` must be one of 'auto', 'manual', ''"),
        ({"propose": "yes"}, "`propose` must be a boolean"),
        ({"targets": "m1"}, "`targets` must be a array"),
        ({"targets": [1]}, "`targets` must be a list of strings"),
        ({"extra": "x"}, "`extra` is not an argument of this tool"),
    ],
)
def test_a_wrong_input_says_what_is_wrong(change, problem):
    assert tools.validate(SCHEMA, {**GOOD, **change}) == [problem]


def test_missing_arguments_and_non_objects_are_refused():
    assert tools.validate(SCHEMA, {"duration": "5m"}) == [
        "`mode` is missing", "`targets` is missing", "`propose` is missing"
    ]
    assert tools.validate(SCHEMA, "timer 5m") == ["the input must be an object"]


# --- back to the words a typed command would have ----------------------------
def test_arguments_become_the_words_after_the_command():
    assert tools.to_args([DURATION, LABEL], {"duration": "1h 30m", "label": "Roast chicken"}) == [
        "1h", "30m", "Roast", "chicken"
    ]
    assert tools.to_args([DURATION, LABEL], {"duration": "5m", "label": "", "propose": True}) == ["5m"]
    assert tools.command_text("timer", ["5m", "tea"]) == "timer 5m tea"
    assert tools.command_text("pomo stats", []) == "pomo stats"


def test_a_timer_tool_call_reads_as_the_typed_word_does(owner):
    timer = by_name(registry.tools_for(owner, INBOX))["timer"].item
    assert split_duration(tools.to_args(timer.params, {"duration": "25m", "label": "laundry"})) == (1500, "laundry")
    assert tools.to_args(timer.params, {"duration": "", "label": ""}) == [], "no arguments lists the timers"


def test_a_pomodoro_tool_call_reads_as_the_typed_word_does(owner):
    pomo = by_name(registry.tools_for(owner, INBOX))["pomo"].item
    plan, label, auto = parse_session(tools.to_args(pomo.params, {"lengths": "50/10", "mode": "auto", "label": "deep work"}))
    assert (plan.focus_s, plan.short_s, label, auto) == (3000, 600, "deep work", True)
    plan, label, auto = parse_session(tools.to_args(pomo.params, {"lengths": "", "mode": "", "label": ""}))
    assert (plan.focus_s, auto) == (1500, None)


def test_dev_settings_read_as_the_typed_word_does(owner, dev_off):
    devmode.enable()
    specs = by_name(registry.tools_for(owner, INBOX))
    assert devmode.parse_number(tools.to_args(specs["dev_speed"].item.params, {"multiplier": "60"}), "") == 60
    assert devmode.parse_on_off(tools.to_args(specs["dev_cleanup"].item.params, {"state": "off"}), "") is False
    assert specs["dev_run"].schema["properties"]["routine"]["enum"] == list(devmode.ROUTINE_NAMES)


# --- which tools are strict --------------------------------------------------
def spec(name, has_arguments=True, priority=0) -> ToolSpec:
    return ToolSpec(name, "", tools.build_schema(), tools.KEYWORD, has_arguments=has_arguments, priority=priority)


def test_only_tools_with_arguments_are_strict():
    strict, overflow = tools.choose_strict([spec("timer"), spec("ping", has_arguments=False)])
    assert strict == {"timer"} and overflow == []


def test_past_the_limit_the_likeliest_come_first():
    specs = [spec("a"), spec("b", priority=5), spec("c"), spec("d", priority=9)]
    strict, overflow = tools.choose_strict(specs, limit=2)
    assert strict == {"d", "b"}
    assert overflow == ["a", "c"], "registration order within a priority"


def test_the_real_tool_sets_fit_within_the_limit(owner, dev_off):
    for dev in (False, True):
        if dev:
            devmode.enable()
        strict, overflow = tools.choose_strict(registry.tools_for(owner, INBOX))
        assert len(strict) <= tools.STRICT_LIMIT and overflow == []
    assert {"timer", "pomo", "help", "timer_control", "pomodoro_control"} <= strict


def test_strict_is_only_put_on_the_chosen_ones():
    assert tools.api_definition(spec("timer"), True) == {
        "name": "timer", "description": "", "input_schema": tools.build_schema(), "strict": True
    }
    assert "strict" not in tools.api_definition(spec("ping"), False)


# --- which message is meant --------------------------------------------------
LISTED = {"m1", "m2", "m3", "m4", "m5", "m6"}


def test_a_reply_always_wins():
    assert tools.resolve_targets(True, ["m2", "m3"], LISTED).kind == REPLY
    assert tools.resolve_targets(True, [], set()).kind == REPLY


def test_one_ref_acts_and_a_few_are_offered():
    assert tools.resolve_targets(False, ["M2 "], LISTED) == tools.Resolution(ONE, ["m2"])
    assert tools.resolve_targets(False, ["m2", "m3", "m2"], LISTED) == tools.Resolution(MANY, ["m2", "m3"])


@pytest.mark.parametrize(
    "refs, words",
    [
        ([], "Call recent_messages"),
        ([""], "Call recent_messages"),
        (["m9"], "Unknown message ref: m9"),
        (["1234567890"], "Unknown message ref"),
        (["m1", "m2", "m3", "m4", "m5", "m6"], "too many to offer"),
    ],
)
def test_no_target_an_unknown_one_or_too_many_goes_back_to_claude(refs, words):
    resolution = tools.resolve_targets(False, refs, LISTED)
    assert resolution.kind == ERROR and words in resolution.error


def test_nothing_can_be_named_before_the_messages_are_listed():
    assert tools.resolve_targets(False, ["m1"], set()).kind == ERROR


# --- words -------------------------------------------------------------------
def test_a_preview_is_one_short_line():
    assert tools.preview("Rent is due\n  on the 1st") == "Rent is due on the 1st"
    assert tools.preview("") == tools.preview(None) == "(no text)"
    assert tools.preview("x" * 200) == "x" * 79 + "…"


def test_a_confirmation_quotes_the_message_and_links_to_it():
    assert tools.confirmation_text("📌 Pinned", "Rent is due", "https://discord.com/x") == (
        "📌 Pinned\n> Rent is due\n-# https://discord.com/x"
    )
    archived = tools.confirmation_text("📦 Archived: https://discord.com/copy", "Rent is due", "https://discord.com/gone")
    assert archived == "📦 Archived: https://discord.com/copy\n> Rent is due", "the outcome already says where it went"


def test_a_destructive_question_quotes_the_target():
    assert tools.question_text("Hive wants to run `delete` that message (delete it).", "Rent is due", "https://x") == (
        "⚠️ Hive wants to run `delete` that message (delete it). Go ahead?\n> Rent is due\n-# https://x"
    )
    assert tools.question_text("Hive wants to run `reset`.") == "⚠️ Hive wants to run `reset`. Go ahead?"


def test_the_listing_gives_each_message_a_ref():
    entries = [
        tools.Listed("m1", "Alex", NOW - timedelta(seconds=30), "Rent is due on the 1st"),
        tools.Listed("m2", "Hive", NOW - timedelta(minutes=5), "⏱️ Tea", ("timer or session card",)),
        tools.Listed("m3", "Alex", NOW - timedelta(hours=3), None, ("pinned", "has files")),
    ]
    assert tools.listing_text(entries, NOW).splitlines()[1:] == [
        "m1: Alex, just now: Rent is due on the 1st",
        "m2: Hive, 5m ago [timer or session card]: ⏱️ Tea",
        "m3: Alex, 3h ago [pinned, has files]: (no text)",
    ]
    assert "no recent messages" in tools.listing_text([], NOW)
    assert tools.age(NOW - timedelta(days=2), NOW) == "2d ago"


# --- which tools are on offer ------------------------------------------------
def test_tools_are_filtered_by_channel(owner):
    inbox, elsewhere = by_name(registry.tools_for(owner, INBOX)), by_name(registry.tools_for(owner, ELSEWHERE))
    assert {"ping", "stats", "reset", "help", "timer", "pomo", "reply_archive", "reply_pin"} <= set(inbox)
    assert {"help", "timer", "reply_archive"} <= set(elsewhere)
    assert not {"ping", "stats", "reset"} & set(elsewhere), "#inbox-only words stay there"


def test_someone_who_may_do_nothing_gets_no_tools(stranger):
    assert registry.tools_for(stranger, INBOX) == []
    assert registry.tools_for(None, INBOX) == []


def test_the_lab_is_never_offered(owner, dev_off):
    for dev in (False, True):
        if dev:
            devmode.enable()
        specs = registry.tools_for(owner, INBOX)
        assert not [spec.name for spec in specs if spec.task == "lab" or spec.name.startswith("lab")]


def test_dev_tools_are_only_offered_while_dev_mode_is_on(owner, dev_off):
    switch = ["dev_mode"]  # the one that is always there, or dev mode could never be asked for
    assert [spec.name for spec in registry.tools_for(owner, INBOX) if spec.task == "dev"] == switch
    devmode.enable()
    names = {spec.name for spec in registry.tools_for(owner, INBOX) if spec.task == "dev"}
    assert {"dev_mode", "dev_speed", "dev_jobs", "reply_dev_inspect"} <= names
    assert not {"dev_on", "dev_off"} & names, "one switch, not three"


def test_the_dev_switch_is_for_the_owner_in_any_channel(owner, stranger, dev_off):
    for channel in (INBOX, ELSEWHERE):
        spec = by_name(registry.tools_for(owner, channel))["dev_mode"]
        assert spec.schema["properties"]["state"]["enum"] == ["on", "off"]
        assert not spec.destructive, "it runs when asked: switching dev mode off loses nothing"
    assert registry.tools_for(stranger, INBOX) == []


def test_dev_tools_are_offered_in_the_dev_channel(owner, dev_off, monkeypatch):
    monkeypatch.setitem(registry.CHANNELS, "dev", 555)
    assert len([spec for spec in registry.tools_for(owner, 555) if spec.task == "dev"]) > 1
    assert [spec.name for spec in registry.tools_for(owner, ELSEWHERE) if spec.task == "dev"] == ["dev_mode"]


def test_the_order_is_the_same_every_time(owner):
    first = [spec.name for spec in registry.tools_for(owner, INBOX)]
    assert first == [spec.name for spec in registry.tools_for(owner, INBOX)], "a changing order would spoil the cache"


def test_every_word_that_takes_arguments_tells_claude_what_they_are(owner, dev_off):
    devmode.enable()
    assert registry.problems() == []
    for spec in registry.tools_for(owner, INBOX):
        if getattr(spec.item, "takes_args", False):
            assert spec.item.params, f"{spec.name} takes arguments but lists none"
            assert spec.has_arguments


def test_a_tool_says_what_typing_it_would_do(owner):
    specs = by_name(registry.tools_for(owner, INBOX))
    assert specs["stats"].description == "Same as the user typing `stats (also: stat)`: all-time usage totals."
    assert specs["reply_pin"].description.startswith("Message action: pin that message at once")


def test_reversible_message_actions_can_be_undone(owner):
    specs = by_name(registry.tools_for(owner, INBOX))
    for name in ("reply_archive", "reply_pin", "reply_unpin"):
        assert specs[name].item.undo is not None, name
    for name in ("reply_delete", "reply_ok"):
        assert specs[name].item.undo is None, name


def test_timers_are_controlled_by_id_not_by_finding_a_message(owner):
    specs = by_name(registry.tools_for(owner, INBOX))
    assert not {"reply_pause", "reply_resume", "reply_cancel", "reply_extend"} & set(specs)
    for name, actions in (
        ("timer_control", ["pause", "resume", "cancel", "stop", "extend"]),
        ("pomodoro_control", ["pause", "resume", "start", "skip", "stop", "extend"]),
    ):
        schema = specs[name].schema
        arguments = ["ids", "action", "duration", "label"] if name == "timer_control" else ["id", "action", "duration"]
        assert list(schema["properties"]) == [*arguments, "propose"]
        assert schema["properties"]["action"]["enum"] == actions
        assert tools.TARGETS not in schema["properties"], "no message to look for"
        assert specs[name].kind == tools.BESPOKE and not specs[name].reads_only


def test_the_tools_that_read_state_take_nothing_and_do_nothing(owner):
    specs = by_name(registry.tools_for(owner, INBOX))
    for name in ("list_timers", "get_pomodoro_status"):
        assert specs[name].reads_only and specs[name].schema["properties"] == {}
    assert {"list_timers", "get_pomodoro_status", "timer_control"} <= set(by_name(registry.tools_for(owner, ELSEWHERE)))


# --- looking further back ----------------------------------------------------
def logged(message_id: int, content: str, days_ago: float = 0) -> tools.Logged:
    return tools.Logged(message_id, content, NOW - timedelta(days=days_ago))


LOG = [
    logged(5, "Show my timers", 0.01),
    logged(4, "What's the capital of Spain", 0.2),
    logged(3, "I'm getting distracted", 0.3),
    logged(2, "What's the capitol of France", 1),
    logged(1, "Spain trip: book flights", 40),
]


def test_the_words_worth_matching_on():
    assert tools.search_terms("the message about the asking for the capital of Spain") == ["capital", "spain"]
    assert tools.search_terms("geting distracted") == ["geting", "distracted"]
    assert tools.search_terms("the one about it") == []


def test_the_best_match_comes_first_then_the_newest():
    found = tools.find_logged(LOG, "capital Spain", NOW)
    assert [row.message_id for row in found] == [4, 2], "both words, then one (a letter out); too old is left out"


def test_a_typo_of_one_letter_still_finds_it():
    assert [row.message_id for row in tools.find_logged(LOG, "geting distracted", NOW)] == [3]


def test_only_the_last_thirty_days_are_searched():
    assert tools.find_logged(LOG, "flights", NOW) == []
    assert [row.message_id for row in tools.find_logged(LOG, "flights", NOW, days=60)] == [1]


def test_the_message_doing_the_asking_is_never_a_match():
    asking = logged(9, "Archive the message about the capital of Spain")
    found = tools.find_logged([asking, *LOG], "capital Spain", NOW, skip=frozenset({9}))
    assert 9 not in [row.message_id for row in found]


def test_a_message_logged_twice_is_found_once():
    assert len(tools.find_logged([LOG[1], LOG[1]], "Spain", NOW)) == 1


def test_nothing_to_match_on_finds_nothing():
    assert tools.find_logged(LOG, "the one about it", NOW) == []


def test_an_older_listing_says_the_user_will_be_asked():
    entry = tools.Listed("s1", "Alex", NOW - timedelta(days=3), "What's the capital of Spain")
    text = tools.listing_text([entry], NOW, tools.OLDER_HEADER)
    assert "asked to confirm" in text.splitlines()[0]
    assert text.splitlines()[1] == "s1: Alex, 3d ago: What's the capital of Spain"
