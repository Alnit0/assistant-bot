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
    assert {"checklist", "confirm-card", "reset-card"} <= set(mock.names())
    for name in mock.names():
        assert mock.parse(mock.read(name)), name
    assert mock.parse(mock.read("checklist"))[0] == Text("# 💊 Today · 2 of 5 taken\n-# Sunday 12 October")
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
