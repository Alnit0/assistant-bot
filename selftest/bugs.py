"""A self-test step that fails is a bug in the forum, until it passes again.

    python -m selftest.bugs --dev <the run's results.json>

Started by `python -m selftest` after a run, once the dev database is back
in its place: the bugs are dev bugs (D numbers), so they are kept in that
database, never in the run's own, which is thrown away. Over HTTP only: no
bot is started and nothing is connected to the gateway.

  - the first step to fail in a stage gets a bug, with what was expected and
    seen; the steps that failed after it in that stage are listed inside it
    as probably following from it, and get none of their own
  - one that fails again adds a note to its bug (re-opening it if it had been
    marked Fixed; a Won't fix stays as you left it)
  - one that passes again marks its bug Fixed, with a note

Only a bug the self-test opened itself is ever touched: the number on record
for a step must be a bug from the self-test about that step, or it is
forgotten (the dev database was recreated, and the number is someone else's).

Which step has which bug is data/selftest/bugs.json. What was done is
printed as JSON, a line an act, for the run's summary.
"""
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("assistant")

BAD = ("fail", "error")
NEW, AGAIN, REOPENED, FIXED = "opened", "failed again", "re-opened", "fixed"
CLIP = 900  # how much of what was seen goes in a post or a note


STAGE_OF = {"p1": "day", "p2": "day", "p3": "day", "p4": "day", "p5": "briefing", "p6": "tidy"}  # a start belongs to the stage it is run for first


@dataclass(frozen=True)
class Act:
    kind: str
    step: str
    number: int | None = None  # the bug it has already
    after: tuple[str, ...] = ()  # the steps that failed after it in its stage: probably following from it
    follows: str = ""  # for a step with a bug of its own that failed after another: that other step


def stage_of(result: dict) -> str:
    """The stage a step belongs to, from the start it ran in (a step recorded
    without one: the part of its number before the dot)."""
    phase = result.get("phase") or ""
    return STAGE_OF.get(phase) or phase or result["key"].split(".")[0]


def firsts(results: list[dict]) -> dict[str, tuple[str, ...]]:
    """{the first step that failed in each stage: the steps that failed after it there}."""
    by_stage: dict[str, list[str]] = {}
    for each in results:
        if each["status"] in BAD:
            by_stage.setdefault(stage_of(each), []).append(each["key"])
    return {failed[0]: tuple(failed[1:]) for failed in by_stage.values()}


def decide(results: list[dict], known: dict[str, int], states: dict[int, str], open_: str, fixed: str) -> list[Act]:
    """What to do about each step of a run. `known` is {step: bug number} and
    `states` {bug number: its status now}; a bug that is no longer in the
    database (the dev database was recreated) is forgotten. Only the first
    step to fail in a stage gets a new bug: what failed after it there most
    likely follows from it, and is listed in that bug. A step that has a bug
    already keeps being told in it, first or not. A step that was skipped, or
    not part of this run, changes nothing."""
    heads = firsts(results)
    behind = {step: head for head, after in heads.items() for step in after}
    acts = []
    for each in results:
        step, number = each["key"], known.get(each["key"])
        state = states.get(number) if number is not None else None
        if each["status"] in BAD:
            if state is not None:
                acts.append(Act(REOPENED if state == fixed else AGAIN, step, number, heads.get(step, ()), behind.get(step, "")))
            elif step in heads:
                acts.append(Act(NEW, step, None, heads[step]))
        elif each["status"] == "pass" and state == open_:
            acts.append(Act(FIXED, step, number))
    return acts


def _clip(text: str, limit: int = CLIP) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def about(step: str) -> str:
    """How a bug's words begin, which is also how a bug is known to be this step's."""
    return f"Self-test step {step}: "


def following(after: list[dict]) -> str:
    """The steps that failed after the one a bug is about, a line each."""
    if not after:
        return ""
    lines = [f"- {each['key']} {_clip(each['title'], 80)}" for each in after[:12]]
    if len(after) > 12:
        lines.append(f"- and {len(after) - 12} more")
    return "\nFailed after it in the same stage, probably following from it:\n" + "\n".join(lines)


def content(result: dict, after: list[dict] = ()) -> str:
    """What the bug's post quotes: the step, what was expected, what was seen,
    and the steps that failed after it."""
    return (
        f"{about(result['key'])}{result['title']}\n"
        f"Expected: {_clip(result.get('expect') or 'nothing said')}\n"
        f"Seen: {_clip(result.get('saw') or 'nothing said')}"
        + following(list(after))
    )


def note(kind: str, result: dict, when: str, commit: str, after: list[dict] = (), follows: str = "") -> str:
    at = f"{when} · commit `{commit or '?'}`"
    if kind == FIXED:
        return f"Passed again in the self-test of {at}: marked Fixed by the self-test."
    lead = "Failed again" if kind == AGAIN else "Failed again, so re-opened,"
    behind = f" This time after step {follows} had failed in the same stage, so probably following from it." if follows else ""
    return f"{lead} in the self-test of {at}.{behind}\nSeen: {_clip(result.get('saw') or 'nothing said')}" + following(list(after))


def line(kind: str, name: str, step: str, url: str | None = None, after: list[str] = ()) -> str:
    """One act, for the run's summary: "D3 opened · step 6.04 (and 6.05, 6.07 after it)"."""
    shown = f"[{name}](<{url}>)" if url else name
    rest = f" (and {', '.join(after[:6])}{'…' if len(after) > 6 else ''} after it)" if after else ""
    return f"{shown} {kind} · step {step}{rest}"


def read_known(where: Path) -> dict[str, int]:
    try:
        return {str(step): int(number) for step, number in json.loads(where.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def has_known(where: Path) -> bool:
    return bool(read_known(where))


# --- doing it (the dev database and the forum) ---------------------------------------------------------------------
async def apply(run: dict, where: Path, user_id: int, forum=None) -> list[dict]:
    """Bring the bugs up to date with a run. One step that can't be dealt with
    is logged and left for the next run; the others are still done."""
    from tasks.bugs import posts, rules, store

    known = read_known(where)
    states = {}
    for step, number in known.items():
        item = await store.get(number)
        # Only a bug the self-test opened itself, about this very step: a number that is now
        # someone else's bug (the dev database was recreated) is never noted on or closed
        if item is not None and item.report.source == rules.SELFTEST and item.report.target.content.startswith(about(step)):
            states[number] = item.status
    by_step = {each["key"]: each for each in run["results"]}
    when = datetime.now(timezone.utc).isoformat()
    commit = run.get("commit") or ""
    done = []
    for act in decide(run["results"], known, states, rules.OPEN, rules.FIXED):
        result, after = by_step[act.step], [by_step[step] for step in act.after]
        try:
            if act.kind == NEW:
                report = rules.Report(
                    source=rules.SELFTEST, channel_id=int(run.get("channel_id") or 0), channel="the self-test",
                    target=rules.Snapshot(0, "self-test", content(result, after), when), commit=commit or "unknown", reported_at=when,
                )
                number = await store.add(user_id, report)
                thread_id, url = await posts.create_post(number, report, forum)
                await store.set_post(number, thread_id, url)
                known[act.step] = number
                # At once: a second post is never made for a step, whatever happens to the rest
                where.parent.mkdir(parents=True, exist_ok=True)
                where.write_text(json.dumps(known, indent=1), encoding="utf-8")
            else:
                number = act.number
                said = note(act.kind, result, run.get("date", ""), commit, after, act.follows)
                await store.add_note(number, user_id, rules.SELF_TEST, said, None)
                if act.kind == FIXED:
                    await store.set_status(number, rules.FIXED, user_id)
                elif act.kind == REOPENED:
                    await store.set_status(number, rules.OPEN, user_id)
                await posts.bring_up_to_date(await store.get(number), said, forum)
            item = await store.get(number)
            done.append({"step": act.step, "bug": rules.bug_id(number), "what": act.kind, "url": item.post_url if item else None, "after": list(act.after)})
        except Exception as error:  # this step's bug is left as it was; the next run looks again
            log.exception("Self-test: the bug for step %s could not be brought up to date", act.step)
            done.append({"step": act.step, "bug": "", "what": f"could not be recorded ({error})", "url": None})
    return done


async def connected(run: dict, where: Path) -> list[dict]:
    """`apply`, with the dev database made ready and Discord reached over HTTP."""
    import discord

    from core import config, discord_utils
    from core.migrations import migrate
    from core.users import ensure_owner, get_user_by_discord_id
    from tasks import registry
    from tasks.bugs import posts

    registry.load()
    migrate(registry.task_migrations())
    ensure_owner()
    owner = await get_user_by_discord_id(int(config.OWNER_ID))
    client = discord.Client(intents=discord.Intents.none())
    await client.login(config.TOKEN)
    discord_utils.client = client
    try:
        return await apply(run, where, owner.id, await posts.fetched_forum())
    finally:
        await client.close()


def main() -> int:
    from core import config

    if not config.DEV_DATABASE:
        print("The self-test's bugs are dev bugs: start this with --dev.", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    run = json.loads(Path(sys.argv[-1]).read_text(encoding="utf-8"))
    for each in asyncio.run(connected(run, config.DATA_DIR / "selftest" / "bugs.json")):
        print(json.dumps(each, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
