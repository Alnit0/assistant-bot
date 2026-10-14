"""Design options, to look at on the phone: `python -m selftest.options`.

Two or three sketched variants of each main card (the checklist, the
reminder, the briefing, the confirm card, the question card) are posted by the
dev bot as real Components V2 messages, each under a line saying which it is
and what is different, with a summary on top to answer with picks.

They go in a post of the dev bot's own forum ("🎨 Design options · <date>"),
not in its other channels: those are emptied at the start of every self-test,
and these are meant to stay until they have been looked at.

Nothing here changes a real card: they are sketches (`docs/mockups/options/`,
in the format `dev mock` reads), and option A of each is the card as it is
built today. A pick is built afterwards, when it has been made.

Over HTTP only, as the dev bot: no bot is started, and live is not touched.
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from core import config

FOLDER = config.MOCKUPS_DIR / "options"
INDEX = "INDEX"
CARDS = ("checklist", "reminder", "briefing", "confirm", "question")  # the order they are posted in
TITLE = "🎨 Design options"


def round_folder(number: int) -> Path:
    """Where a later round's sketches are: docs/mockups/options/round-2/. Round 1 is the folder itself."""
    return FOLDER if number <= 1 else FOLDER / f"round-{number}"


def listed(folder: Path = FOLDER) -> list[tuple[str, str, str]]:
    """(file name, label, what is different) for each sketch, in the order posted: round 1 by card, then by
    letter; a later round in the order of its INDEX."""
    found = []
    for line in (folder / INDEX).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, label, differs = (part.strip() for part in line.split("|", 2))
            found.append((name, label, differs))
    if folder != FOLDER:
        return found
    return sorted(found, key=lambda each: (CARDS.index(each[0].rsplit("-", 1)[0]), each[0]))


def _example(options: list[tuple[str, str, str]]) -> str:
    """An answer as one might type it, from the round's own labels: the first sketch of each card."""
    first: dict[str, str] = {}
    for _, label, _ in options:
        card, _, which = label.partition(" · ")
        first.setdefault(card.lower(), which)
    return ", ".join(f"{card} {which}" for card, which in list(first.items())[:3])


def round_summary(number: int, options: list[tuple[str, str, str]]) -> str:
    """What opens a later round, in the same post as the first."""
    return "\n".join([
        f"**Design options · round {number}** · sketches only, from your feedback on the round before: nothing in the real cards changes until you pick.",
        f"{len(options)} sketches follow, each under a line saying which it is (R{number}-A, R{number}-B…). The buttons on a sketch do nothing.",
        "",
        f"**To pick**, reply here, e.g. `{_example(options)}`, and anything you would change.",
        *(f"- **{label}** · {differs}" for _, label, differs in options),
    ])[:1990]


def summary(options: list[tuple[str, str, str]]) -> str:
    """The post's opening message: what this is, and how to answer."""
    cards = len({name.rsplit("-", 1)[0] for name, _, _ in options})
    return "\n".join([
        "**Design options** · sketches only: nothing in the real cards changes until you pick.",
        f"{len(options)} sketches of {cards} cards follow, each under a line saying which it is. Option **A** of each is the card as it is built today. The buttons on a sketch do nothing.",
        "",
        "**To pick**, reply here with a letter for each, e.g. `checklist B, reminder A, briefing B, confirm A, question C`, and anything you would change about one.",
        "The list of them all is the next message.",
    ])


def catalogue(options: list[tuple[str, str, str]]) -> str:
    """Every option in a line, card by card: the summary to pick from."""
    lines = []
    for card in CARDS:
        mine = [each for each in options if each[0].rsplit("-", 1)[0] == card]
        if not mine:
            continue
        lines.append(f"**{mine[0][1].split(' · ')[0]}**")
        lines += [f"- **{label.split(' · ')[1]}** · {differs}" for _, label, differs in mine]
    return "\n".join(lines)


def label_line(label: str, differs: str) -> str:
    """The line above a sketch: which it is and what is different about it."""
    return f"### {label}\n-# {differs}"


def checked(folder: Path = FOLDER) -> list[tuple[str, str, str, list]]:
    """Every option, read and within Discord's limits, or a ValueError naming the one that is not."""
    from tasks.dev import mock

    found = []
    for name, label, differs in listed(folder):
        try:
            pieces = mock.parse((folder / f"{name}.txt").read_text(encoding="utf-8"))
        except mock.MockError as error:
            raise ValueError(f"{name}: {error}") from error
        if mock.count(pieces) > mock.MAX_COMPONENTS or mock.length(pieces) > mock.MAX_TEXT:
            raise ValueError(f"{name}: too big for one message ({mock.count(pieces)} components, {mock.length(pieces)} characters)")
        found.append((name, label, differs, pieces))
    return found


def picked(options: list, only: tuple[str, ...] = ()) -> list:
    """The sketches to post: all of them, or just those named (`--only a,b`), in the round's order. A name
    that is not in the round stops it: nothing is posted for a slip of the hand."""
    if not only:
        return options
    unknown = sorted(set(only) - {each[0] for each in options})
    if unknown:
        raise SystemExit(f"Not in this round: {', '.join(unknown)}. Nothing posted.")
    return [each for each in options if each[0] in only]


async def _earlier_post(client, forum):
    """The design-options post that is already there, the latest one, or None. Asked over HTTP: there is no cache."""
    found = await client.http.get_active_threads(forum.guild.id)
    mine = [each for each in found.get("threads", []) if str(each.get("parent_id")) == str(forum.id) and (each.get("name") or "").startswith(TITLE)]
    if mine:
        return await client.fetch_channel(int(max(mine, key=lambda each: int(each["id"]))["id"]))
    async for thread in forum.archived_threads(limit=50):
        if thread.name.startswith(TITLE):
            return thread
    return None


async def post_round(number: int, when: datetime, only: tuple[str, ...] = ()) -> str:
    """Post a later round's sketches in the design-options post that is already
    there (a new one only if that can't be found). Returns its link. With
    `only`, just the sketches named: for adding to a round already posted."""
    import discord
    from dotenv import dotenv_values

    from tasks.dev import mock

    token, expected = config.test_bot_token(), config.test_bot_id()
    if token is None or expected is None:
        raise SystemExit("There is no dev bot (.env.dev needs its own token and BOT_USER_ID): nothing posted.")
    forum_id = (dotenv_values(config.BASE_DIR / ".env.dev").get("BUGS_CHANNEL_ID") or "").strip()
    if not forum_id.isdigit():
        raise SystemExit("BUGS_CHANNEL_ID is not set in .env.dev: the options go in the dev bot's forum. Nothing posted.")
    options = picked(checked(round_folder(number)), only)
    client = discord.Client(intents=discord.Intents.none())
    await client.login(token)
    try:
        if client.user.id != expected:
            raise SystemExit("Not the dev bot's account: nothing posted.")
        forum = await client.fetch_channel(int(forum_id))
        if not isinstance(forum, discord.ForumChannel):
            raise SystemExit("BUGS_CHANNEL_ID in .env.dev is not a forum: nothing posted.")
        quiet = discord.AllowedMentions.none()
        opening = round_summary(number, [each[:3] for each in options])
        thread = await _earlier_post(client, forum)
        if thread is None:
            made = await forum.create_thread(name=f"{TITLE} · round {number} · {when:%Y-%m-%d}", content=opening, allowed_mentions=quiet)
            thread = made.thread
        else:
            await thread.send(opening, allowed_mentions=quiet)
        for _, label, differs, pieces in options:
            await thread.send(label_line(label, differs), allowed_mentions=quiet)
            await thread.send(view=mock.layout(pieces))
        return thread.jump_url
    finally:
        await client.close()


async def post(when: datetime) -> str:
    """Post them all in a new post of the dev bot's forum. Returns its link."""
    import discord
    from dotenv import dotenv_values

    from tasks.dev import mock

    token, expected = config.test_bot_token(), config.test_bot_id()
    if token is None or expected is None:
        raise SystemExit("There is no dev bot (.env.dev needs its own token and BOT_USER_ID): nothing posted.")
    forum_id = (dotenv_values(config.BASE_DIR / ".env.dev").get("BUGS_CHANNEL_ID") or "").strip()
    if not forum_id.isdigit():
        raise SystemExit("BUGS_CHANNEL_ID is not set in .env.dev: the options go in the dev bot's forum. Nothing posted.")
    options = checked()
    client = discord.Client(intents=discord.Intents.none())
    await client.login(token)
    try:
        if client.user.id != expected:
            raise SystemExit("Not the dev bot's account: nothing posted.")
        forum = await client.fetch_channel(int(forum_id))
        if not isinstance(forum, discord.ForumChannel):
            raise SystemExit("BUGS_CHANNEL_ID in .env.dev is not a forum: nothing posted.")
        quiet = discord.AllowedMentions.none()
        made = await forum.create_thread(name=f"{TITLE} · {when:%Y-%m-%d}", content=summary([each[:3] for each in options]), allowed_mentions=quiet)
        await made.thread.send(catalogue([each[:3] for each in options]), allowed_mentions=quiet)
        for _, label, differs, pieces in options:
            await made.thread.send(label_line(label, differs), allowed_mentions=quiet)
            await made.thread.send(view=mock.layout(pieces))
        return made.thread.jump_url
    finally:
        await client.close()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    number = int(sys.argv[sys.argv.index("--round") + 1]) if "--round" in sys.argv[1:] else 1
    if "--check" in sys.argv[1:]:
        print(f"{len(checked(round_folder(number)))} sketches read, each within one message.")
        return 0
    only = tuple(part.strip() for part in sys.argv[sys.argv.index("--only") + 1].split(",") if part.strip()) if "--only" in sys.argv[1:] else ()
    print("Posted:", asyncio.run(post(datetime.now()) if number <= 1 else post_round(number, datetime.now(), only)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
