"""`dev mock` (tasks/dev/mock.py): a card sketched in a text file, read into plain records
and built as a Components V2 message. Every mistake is reported with its line number."""
import asyncio
from types import SimpleNamespace

import discord
import pytest

from core import cards
from core.config import MOCKUPS_DIR
from tasks import registry
from tasks.dev import mock
from tasks.dev.mock import Button, Container, MockError, Row, Separator, Text

SKETCH = """# 💊 Today · 2 of 5 taken
-# Sunday 12 October

┃ accent: amber
┃ **Pill A** · ●○○
┃ -# with no food
┃ ---
┃ [✅ Taken: green] [⏭️ Skip: blurple]

┃ **Pill B**
┃ [↩️ Cancel: grey]
---
[🗑️ Delete: red]
"""


def run(coroutine):
    return asyncio.run(coroutine)


def problem(text) -> tuple[int, str]:
    with pytest.raises(MockError) as caught:
        mock.parse(text)
    return caught.value.line, caught.value.problem


# ---------------------------------------------------------------------------
# Reading a sketch (pure)
# ---------------------------------------------------------------------------
def test_a_sketch_is_read_into_text_containers_separators_and_rows():
    assert mock.parse(SKETCH) == [
        Text("# 💊 Today · 2 of 5 taken\n-# Sunday 12 October"),
        Container(
            (
                Text("**Pill A** · ●○○\n-# with no food"),
                Separator(),
                Row((Button("✅ Taken", cards.SUCCESS), Button("⏭️ Skip", cards.PRIMARY))),
            ),
            accent="amber",
        ),
        Container((Text("**Pill B**"), Row((Button("↩️ Cancel", cards.SECONDARY),)))),
        Separator(),
        Row((Button("🗑️ Delete", cards.DANGER),)),
    ]


def test_a_blank_line_starts_a_new_container_and_lines_that_follow_each_other_are_one():
    assert mock.parse("┃ one\n┃ two\n\n┃ three") == [Container((Text("one\ntwo"),)), Container((Text("three"),))]
    assert mock.parse("┃ one\n┃\n┃ two") == [Container((Text("one\ntwo"),))], "an empty line of a container does not end it"


def test_headings_and_subtext_are_left_for_discord_to_write():
    assert mock.parse("┃ ## Heading\n┃ -# small\n┃ **bold**") == [Container((Text("## Heading\n-# small\n**bold**"),))]


def test_what_discord_would_count():
    pieces = mock.parse(SKETCH)
    assert mock.count(pieces) == 14 and mock.length(pieces) == len("# 💊 Today · 2 of 5 taken\n-# Sunday 12 October") + len("**Pill A** · ●○○\n-# with no food") + len("**Pill B**")


@pytest.mark.parametrize(
    "text, line, says",
    [
        ("", 1, "the sketch is empty"),
        ("\n\n", 1, "the sketch is empty"),
        ("┃ accent: pink\n┃ hello", 1, "“pink” is not an accent colour: use amber, blue, blurple, green, grey, red, yellow"),
        ("┃ hello\n┃ accent: red", 2, "the accent is the first line of its container"),
        ("accent: red\nhello", 1, "an accent belongs to a container: start the line with ┃"),
        ("┃ accent: red", 1, "this container has nothing in it"),
        ("┃ hello\n┃ [Save: purple]", 2, "“purple” is not a button colour: use blurple, green, grey, red"),
        ("┃ hello\n\n┃ [Save]", 3, "a button is written [label: colour], not [Save]"),
        ("[: green]", 1, "a button is written [label: colour], not [: green]"),
        ("┃ [Skip: grey]", 1, "“Skip” is grey: grey is for Cancel only (make it with cards.cancel), and any other choice is blurple"),
        ("┃ [Cancel: blurple]", 1, "“Cancel” must be the grey ↩️ button (make it with cards.cancel)"),
        ("[a: green] [b: green] [c: green] [d: green] [e: green] [f: green]", 1, "a row has at most 5 buttons, not 6"),
        ("one\ntwo\n[a: green] and [b: red]", 3, "buttons go on a line of their own, with no other text beside them"),
    ],
)
def test_a_mistake_is_reported_with_its_line(text, line, says):
    assert problem(text) == (line, says)
    with pytest.raises(MockError, match=f"^line {line}: "):
        mock.parse(text)


def test_more_than_discord_takes_is_refused():
    line, says = problem("\n".join(["---"] * 41))
    assert line == 41 and says.startswith("that makes 41 components, and one message takes 40")
    line, says = problem("x" * 4001)
    assert says == "that is 4001 characters of text, and one message takes 4000"


# ---------------------------------------------------------------------------
# The files
# ---------------------------------------------------------------------------
def test_the_sketches_in_the_repository_all_read(tmp_path):
    assert {"checklist-v2", "confirm-card-v2", "reset-card-v2"} <= set(mock.names())
    for name in mock.names():
        assert mock.parse(mock.read(name)), name
    assert mock.parse(mock.read("checklist-v2"))[0] == Text("# 💊 Today · 2 of 6 taken\n-# Sunday 12 October")
    assert mock.names(tmp_path / "missing") == []


def test_only_a_plain_name_is_looked_for(tmp_path):
    (tmp_path / "card.txt").write_text("hello", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("no", encoding="utf-8")
    assert mock.read("card", tmp_path) == "hello" and mock.read("Card.txt", tmp_path) == "hello"
    assert mock.read("../secret", tmp_path) is None and mock.read("nothing", tmp_path) is None and mock.read("", tmp_path) is None


def test_the_list():
    assert mock.list_text(["checklist", "reset-card"]).splitlines() == ["🧪 **Mock-ups** · `dev mock <name>` posts one here", "• `checklist`", "• `reset-card`"]
    assert mock.list_text([]) == "🧪 No mock-ups yet: put a sketch in `docs/mockups/<name>.txt`."


# ---------------------------------------------------------------------------
# Discord's side
# ---------------------------------------------------------------------------
def test_the_records_become_a_components_v2_message():
    built = mock.layout(mock.parse(SKETCH))
    assert isinstance(built, discord.ui.LayoutView) and built.timeout is None
    top, first, second, line, row = built.to_components()
    assert top == {"type": 10, "content": "# 💊 Today · 2 of 5 taken\n-# Sunday 12 October"}
    assert first["type"] == 17 and first["accent_color"] == mock.ACCENTS["amber"] and [each["type"] for each in first["components"]] == [10, 14, 1]
    assert second.get("accent_color") is None and line["type"] == 14 and row["type"] == 1
    buttons = [*first["components"][2]["components"], *second["components"][1]["components"], *row["components"]]
    assert [(each["label"], each["style"]) for each in buttons] == [("✅ Taken", 3), ("⏭️ Skip", 1), ("↩️ Cancel", 2), ("🗑️ Delete", 4)]
    assert [each["custom_id"] for each in buttons] == ["dev:mock:1", "dev:mock:2", "dev:mock:3", "dev:mock:4"], "each its own id"


def test_a_mock_ups_button_only_says_that_it_is_one(owner, stranger, monkeypatch):
    said = []

    async def safe_reply(interaction, text, ephemeral=True):
        said.append(text)

    async def user_of(discord_id):
        return owner if discord_id == owner.discord_id else stranger

    monkeypatch.setattr(mock, "safe_reply", safe_reply)
    monkeypatch.setattr(mock, "get_user_by_discord_id", user_of)
    button = mock.MockButton(3)
    run(button.callback(SimpleNamespace(user=SimpleNamespace(id=owner.discord_id))))
    run(button.callback(SimpleNamespace(user=SimpleNamespace(id=stranger.discord_id))))
    assert said == ["🧪 Mock-up: this button does nothing yet.", "That isn't yours to press."]


class Ctx:
    def __init__(self, *args):
        self.args, self.replies, self.sent, self.noted = list(args), [], [], []
        self.channel = SimpleNamespace(send=self._send)

    async def reply(self, text, view=None):
        self.replies.append(text)

    async def _send(self, view=None, silent=False):
        self.sent.append(view)

    def shown(self, text):
        self.noted.append(text)


@pytest.fixture
def sketches(tmp_path, monkeypatch):
    monkeypatch.setattr(mock, "MOCKUPS_DIR", tmp_path)
    (tmp_path / "good.txt").write_text("┃ hello\n┃ [✅ Save: green]", encoding="utf-8")
    (tmp_path / "bad.txt").write_text("┃ hello\n┃ [Save: purple]", encoding="utf-8")
    return tmp_path


def test_dev_mock_alone_lists_the_sketches(sketches):
    ctx = Ctx()
    assert run(mock.mock(ctx)) == "listed 2 mock-up(s)"
    assert ctx.replies == ["🧪 **Mock-ups** · `dev mock <name>` posts one here\n• `bad`\n• `good`"]


def test_dev_mock_with_a_name_posts_it_in_the_channel(sketches):
    ctx = Ctx("good")
    assert run(mock.mock(ctx)) == "posted the mock-up good (4 components)"
    (view,) = ctx.sent
    assert isinstance(view, discord.ui.LayoutView) and ctx.replies == [] and ctx.noted == ["mock-up: good"]


def test_a_sketch_that_cannot_be_read_is_said_with_the_line_number_and_nothing_is_posted(sketches):
    ctx = Ctx("bad")
    assert run(mock.mock(ctx)).startswith("mock-up bad not posted: line 2: ")
    assert ctx.sent == [] and ctx.replies == ["⚠️ `docs/mockups/bad.txt`, line 2: “purple” is not a button colour: use blurple, green, grey, red"]


def test_a_name_there_is_no_sketch_for_is_said_with_the_ones_there_are(sketches):
    ctx = Ctx("nothing")
    assert run(mock.mock(ctx)) == "no mock-up called nothing"
    assert ctx.sent == [] and ctx.replies[0].splitlines()[0] == "🧪 There is no mock-up called `nothing`."


def test_dev_mock_is_a_typed_word_of_the_dev_task():
    registry.load()
    kind, task, item = registry.find("dev mock")
    assert (kind, task.name, item.takes_args, item.permission) == ("keyword", "dev", True, "dev")
    assert MOCKUPS_DIR.name == "mockups" and MOCKUPS_DIR.parent.name == "docs"


def test_every_sketch_in_the_repository_reads_and_fits_a_message():
    # The reminder mock-ups among them
    found = mock.names()
    assert {"checklist-v2", "reminder-v1", "reminder-renudge-v2", "reminder-missed-v2", "too-soon-v2"} <= set(found)
    for name in found:
        pieces = mock.parse(mock.read(name))
        assert 0 < mock.count(pieces) <= mock.MAX_COMPONENTS, name


def test_no_reminder_sketch_names_a_pill_in_the_line_the_lock_screen_shows():
    # A notification shows the first line of the message: it says a routine is due, and when
    for name in ("reminder-v1", "reminder-v1-first", "reminder-renudge-v2"):
        first = mock.read(name).splitlines()[0]
        assert first.startswith("💊 Dose due · ") and "Pill" not in first, name


def test_the_gym_sketches_are_there_and_the_plan_cards_follow_the_card_rules():
    assert {"gym-import-v2", "gym-change-v2", "gym-workout-v1", "gym-logged-set-v2"} <= set(mock.names())
    assert "## 🏋️ Gym · new" in mock.read("gym-import-v2") and "## 🏋️ Gym · change" in mock.read("gym-change-v2")
    # A change is `field · old → new`; what is not used is named; Save is green and Cancel the one grey button
    change = mock.read("gym-change-v2")
    assert "weight · 60 kg → 62.5 kg" in change and "Not used:" in change and "Not used:" in mock.read("gym-import-v2")
    for name in ("gym-import-v2", "gym-change-v2"):
        assert "[✅ Save: green] [↩️ Cancel: grey]" in mock.read(name), name


# --- the Components V2 design pass (docs/DESIGN.md) ---------------------------------------------------
DESIGNED = (
    "checklist-v2", "reminder-v1", "reminder-v1-first", "confirm-card-v2", "question-card-v1", "reset-card-v2", "gym-workout-v1",
    "too-soon-v2", "reminder-renudge-v2", "reminder-missed-v2", "gym-import-v2", "gym-change-v2", "gym-logged-set-v2",
    "briefing-v1", "schedule-list-v1", "schedule-change-v1", "cleanup-v1", "briefing-v2", "schedule-list-v2",
)


@pytest.mark.parametrize("name", DESIGNED)
def test_each_designed_sketch_renders_as_a_components_v2_message_within_the_limits(name):
    pieces = mock.parse(mock.read(name))
    assert mock.count(pieces) <= mock.MAX_COMPONENTS and mock.length(pieces) <= mock.MAX_TEXT
    built = mock.layout(pieces).to_components()  # what `dev mock` would send
    assert built and all(each["type"] in (1, 10, 14, 17) for each in built)
    if name != "reminder-v1-first":
        assert mock.read(name).strip().splitlines()[-1].startswith("-# 🧪 "), "its last line says the version and what was simplified"


def test_the_reminder_is_first_posted_as_one_line_that_names_no_pill():
    first = mock.read("reminder-v1-first").strip()
    assert first == "💊 Dose due · 11:12 am"
    assert mock.read("reminder-v1").splitlines()[0] == first, "the same line stays on top once the pill is written in"
    assert "Pill A" in mock.read("reminder-v1")


def test_the_designed_cards_keep_the_card_rules():
    assert "[✅ Save: green] [↩️ Cancel: grey]" in mock.read("confirm-card-v2") and "→" in mock.read("confirm-card-v2") and "❓" in mock.read("confirm-card-v2")
    question = mock.read("question-card-v1")
    assert "Save" not in question.split("🧪")[0].replace("no Save", "") and "[8:00 am: blurple] [8:00 pm: blurple] [↩️ Cancel: grey]" in question
    assert "accent: red" in mock.read("reset-card-v2") and "[🗑️ Delete all: red]" in mock.read("reset-card-v2")
    # A status has its colour: due amber, any time and still to take blue, taken green, missed red, paused grey
    checklist = mock.read("checklist-v2")
    assert all(f"accent: {colour}" in checklist for colour in ("amber", "blue", "green", "red", "grey"))
    assert "┃ accent: blue\n┃ **Pill B** · ○ · any time" in checklist.replace("\r\n", "\n")
    # A card that asks first because something is risky is amber, and its ⚠️ line says why
    risky = mock.read("too-soon-v2")
    assert risky.startswith("┃ accent: amber") and "⚠️" in risky and "[✅ Log it: green] [↩️ Cancel: grey]" in risky
    # Asked again is still due (amber); snoozed is grey
    assert "accent: amber" in mock.read("reminder-renudge-v2") and "accent: grey" in mock.read("reminder-renudge-v2")
    # A missed dose is a ❌ line; the box is amber while a dose is still to come, red only when none is
    missed = mock.read("reminder-missed-v2")
    assert "accent: amber" in missed and "accent: red" not in missed and "❌ dose 2 · missed" in missed and "**Next:** dose 3" in missed
    assert "accent: red\n┃ **Pill E** · ✕" in checklist.replace("\r\n", "\n")
    design = (mock.MOCKUPS_DIR.parent / "DESIGN.md").read_text(encoding="utf-8")
    assert all(f"`{name}`" in design for name in DESIGNED)


def test_every_sketch_carries_its_version_in_its_name_and_the_ones_replaced_are_gone():
    assert set(mock.names()) == set(DESIGNED)
    assert all(name.removesuffix("-first").rpartition("-v")[2].isdigit() for name in mock.names())


def test_the_scheduler_and_briefing_sketches_keep_the_card_and_hub_rules():
    # The briefing is a standing message with a box a task and no buttons: things are done on the task's own message
    briefing = mock.read("briefing-v2")
    assert briefing.startswith("# ☀️ Today") and "💊 **Pills**" in briefing and "Yesterday:" in briefing and "[" not in briefing.split("🧪")[0]
    # It always shows now: nothing says when it was written
    assert "as of" not in briefing.split("🧪")[0]
    # The list has no buttons either: every change to a schedule is by words, on a card
    listed = mock.read("schedule-list-v2")
    assert listed.startswith("# 🗓️ My schedule") and "⏸️ **Paused**" in listed and "[" not in listed.split("🧪")[0]
    # The morning routine: tidy, then the briefing, then the checklist, so the checklist is the newest message
    steps = listed.replace("\r\n", "\n")
    assert "┃ 1. 🧹 Tidy\n┃ 2. ☀️ Briefing\n┃ 3. 💊 Pills checklist" in steps
    change = mock.read("schedule-change-v1")
    assert change.startswith("┃ accent: blurple") and "## 🗓️ Schedule · change" in change and "→" in change
    assert "[✅ Save: green] [↩️ Cancel: grey]" in change and "Not included:" in change
    # A tidy has no buttons, and says that one with nothing wrong posts nothing
    tidy = mock.read("cleanup-v1")
    assert "[" not in tidy.split("🧪")[0] and "posts nothing" in tidy
