from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Pending proposals: something Claude has suggested and the user has not yet
# agreed to. A short "ok" within two minutes runs it; "no" drops it; anything
# else drops it too and is treated as an ordinary message.
#
# Held in memory, one per user and channel: a new proposal replaces the old
# one, and a restart forgets them (the user just asks again).
# ---------------------------------------------------------------------------
EXPIRY_SECONDS = 120

YES, NO = "yes", "no"

_YES = {
    "ok", "okay", "k", "yes", "yep", "yeah", "yup", "y", "sure", "do it", "go ahead", "go for it",
    "please do", "yes please", "ok do it", "sounds good", "👍",
}
_NO = {"no", "nope", "nah", "n", "cancel", "never mind", "nevermind", "don't", "dont", "no thanks", "stop", "👎"}


def classify(text: str) -> str | None:
    """YES or NO if the whole message is a short answer to a proposal, else None."""
    answer = " ".join(text.strip().lower().rstrip(".!").split())
    if answer in _YES:
        return YES
    if answer in _NO:
        return NO
    return None


@dataclass(frozen=True)
class Proposal:
    call: object  # whatever the proposer needs to run it later
    summary: str  # what was proposed, in words
    expires_at: datetime  # UTC


_pending: dict[tuple[int, int], Proposal] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def propose(channel_id: int, user_id: int, call, summary: str, now: datetime | None = None) -> Proposal:
    """Remember a proposal for this user in this channel, replacing any earlier one."""
    proposal = Proposal(call, summary, (now or _now()) + timedelta(seconds=EXPIRY_SECONDS))
    _pending[(channel_id, user_id)] = proposal
    return proposal


def take(channel_id: int, user_id: int, now: datetime | None = None) -> Proposal | None:
    """Remove and return this user's proposal here, or None if there is none or it has expired."""
    proposal = _pending.pop((channel_id, user_id), None)
    if proposal is None or proposal.expires_at <= (now or _now()):
        return None
    return proposal


def waiting(channel_id: int, user_id: int, now: datetime | None = None) -> bool:
    """Whether a proposal is waiting for this user's "ok" here."""
    proposal = _pending.get((channel_id, user_id))
    return proposal is not None and proposal.expires_at > (now or _now())


def clear() -> None:
    _pending.clear()
