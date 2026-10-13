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


def listed(folder: Path = FOLDER) -> list[tuple[str, str, str]]:
    """(file name, label, what is different) for each sketch, in the order posted: by card, then by letter."""
    found = []
    for line in (folder / INDEX).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, label, differs = (part.strip() for part in line.split("|", 2))
            found.append((name, label, differs))
    return sorted(found, key=lambda each: (CARDS.index(each[0].rsplit("-", 1)[0]), each[0]))


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
    if "--check" in sys.argv[1:]:
        print(f"{len(checked())} sketches read, each within one message.")
        return 0
    print("Posted:", asyncio.run(post(datetime.now())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
