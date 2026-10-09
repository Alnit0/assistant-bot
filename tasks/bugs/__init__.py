import asyncio

import discord

from core.config import BASE_DIR
from core.context import Context
from core.errors import UserError
from core.clock import real_now
from core.users import User
from tasks.base import ANY, Keyword, Reaction, ReplyAction, Task
from tasks.bugs import capture, posts, rules, store

EXPORT_FILE = BASE_DIR / "docs" / "BUGS.md"

# A bug is reported in two ways only: 🐞 on a message, or the word "bug" (as a
# reply for that message, on its own for the latest thing in the channel). No
# note is taken in the channel: each bug gets a post in the #bugs forum, and
# what is written there is saved with it.


async def _file(
    user: User, channel_id: int, target: rules.Snapshot, before: list[rules.Snapshot], source: str,
    exclude_message_id: int | None = None,
) -> str:
    """Log a bug against a message and open its post. Returns the line for the
    channel. A message that already has an open bug is pointed to, not logged twice."""
    existing = await store.open_for(user.id, channel_id, target.message_id)
    if existing is not None:
        return rules.logged_text(existing.id, existing.post_url, existing=True)
    # Before anything is recorded: is there somewhere to put the post?
    posts.forum()
    report = await capture.build(
        source=source, channel_id=channel_id, target=target, preceding=before, exclude_message_id=exclude_message_id
    )
    number = await store.add(user.id, report)
    thread_id, url = await posts.create_post(number, report)
    await store.set_post(number, thread_id, url)
    return rules.logged_text(number, url)


async def report_latest(ctx: Context) -> str:
    if rules.in_bugs_forum(ctx.parent_channel_id):
        raise UserError(rules.IN_POST)
    recent = await ctx.recent_messages(rules.PRECEDING + 1)
    if not recent:
        raise UserError("There is nothing in this channel to report yet.")
    before = [rules.snapshot(message) for message in reversed(recent[1:])]
    text = await _file(ctx.user, ctx.channel_id, rules.snapshot(recent[0]), before, rules.WORD, ctx.message_id)
    await ctx.reply(text)
    return text


async def report_reply(ctx: Context, target: discord.Message) -> str:
    rules.check_reportable(target)
    before = await posts.preceding(target)
    text = await _file(ctx.user, target.channel.id, rules.snapshot(target), before, rules.REPLY, ctx.message_id)
    await ctx.reply(text)
    return text


async def report_reaction(payload: discord.RawReactionActionEvent, user: User) -> str:
    target = await posts.fetch_message(payload.channel_id, payload.message_id)
    rules.check_reportable(target)
    before = await posts.preceding(target)
    text = await _file(user, payload.channel_id, rules.snapshot(target), before, rules.REACTION)
    await posts.send(payload.channel_id, text)
    return text


async def list_bugs(ctx: Context) -> None:
    await ctx.reply(rules.list_text(await store.open_items(ctx.user.id)))


async def export(ctx: Context) -> str:
    entries = await store.in_full(ctx.user.id)
    text = rules.export_text(entries, real_now())
    await asyncio.to_thread(EXPORT_FILE.write_text, text, encoding="utf-8")
    count = len(entries)
    await ctx.confirm(f"📝 Wrote {count} open bug{'' if count == 1 else 's'} to docs/BUGS.md")
    return f"exported {count} open bugs to {EXPORT_FILE.name}"


async def save_note(ctx: Context) -> str:
    """Something written in a bug's post: kept with the bug, and ticked."""
    item = await store.by_thread(ctx.channel_id)
    if item is None:
        return "not a bug's post: left alone"
    await store.add_note(item.id, ctx.user.id, rules.OWNER, ctx.text, ctx.message_id)
    await ctx.acknowledge()
    # The count on the post's opening card, in place
    await posts.refresh_card(await store.get(item.id))
    return f"note saved for {rules.bug_id(item.id)}"


class BugsTask(Task):
    """Reporting bugs: each one captured with its context and given a post in #bugs."""

    name = "bugs"
    description = "Report a bug with 🐞 or `bug`: it is captured with its context and gets a post in #bugs"

    def keywords(self) -> list[Keyword]:
        return [
            Keyword(
                "bug",
                "report the latest exchange in this channel as a bug: it is captured with the messages "
                "before it, the tool calls, timings and errors of that turn, and gets a post in #bugs",
                report_latest,
                examples=["bug"],
                channels=ANY,
            ),
            Keyword(
                "bugs",
                "list the open bugs, each with a link to its post",
                list_bugs,
                examples=["bugs"],
            ),
            Keyword(
                "bugs export",
                "write the open bugs, with everything captured and their notes, to docs/BUGS.md",
                export,
                examples=["bugs export"],
            ),
        ]

    def reply_actions(self) -> list[ReplyAction]:
        return [
            ReplyAction(
                "bug",
                "report that message as a bug: it is captured with its context and gets a post in #bugs",
                report_reply,
                examples=["bug", "bug this"],
                validate=rules.check_reportable,
            ),
        ]

    def reactions(self) -> list[Reaction]:
        return [
            Reaction(
                rules.BUG_EMOJI,
                "report the message as a bug, at once: it is captured with its context and gets a post "
                "in #bugs. Removing the reaction does nothing; close a report with Won't fix on its post",
                report_reaction,
                examples=[f"react {rules.BUG_EMOJI} to a message"],
                validate=rules.check_reportable,
                instant=True,
            ),
        ]

    def claim(self, ctx: Context):
        # Whatever is written in a bug's post is a note for that bug. Never sent to Claude
        return save_note if rules.in_bugs_forum(ctx.parent_channel_id) else None

    def migrations(self) -> list:
        return list(store.MIGRATIONS)

    def setup(self, client: discord.Client) -> None:
        # Before connecting, so the buttons on old posts still work
        client.add_view(posts.CloseButtons())
        client.add_view(posts.ReopenButton())

    async def startup(self, client: discord.Client) -> None:
        await capture.git_commit()
        await posts.ensure_tags()


task = BugsTask()
