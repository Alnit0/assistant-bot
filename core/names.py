"""Which of my things a name means (pills today; any task with named things).

Pure. The whole name wins over part of one; a name that fits more than one
is never guessed: the task is told which ones, and asks. A task supplies how
a thing is named and, if its things have typed ids ("pl3"), their prefix; it
writes its own words for "there is none"."""
import re
from collections.abc import Callable, Sequence

from core.errors import UserError


class Unnamed(UserError):
    """Nothing was named."""

    def __init__(self):
        super().__init__("Which one?")


class Unknown(UserError):
    """No thing has that name: `said` is the name as it was typed."""

    def __init__(self, said: str):
        self.said = said
        super().__init__(f"I don't have one called “{said}”.")


class Ambiguous(UserError):
    """A name that fits more than one thing: `candidates` are the ones it
    could be, and `labels` their names in the same order."""

    def __init__(self, said: str, candidates: Sequence, labels: Sequence[str] = ()):
        self.said, self.candidates = said, list(candidates)
        self.labels = list(labels) or [str(each) for each in candidates]
        super().__init__("Which one: " + " or ".join(f"**{label}**" for label in self.labels) + "?")


def tidy(text: str) -> str:
    """A name as it is compared: lower case, one space between words."""
    return re.sub(r"\s+", " ", text.strip().lower())


def find[T](things: Sequence[T], wanted: str, name: Callable[[T], str], prefix: str = "", id_of: Callable[[T], int] | None = None) -> T:
    """The one of `things` that `wanted` means: by its id if it is written as
    one ("pl3", with `prefix` and `id_of`), else by its whole name, else by
    part of it. Raises Unnamed for nothing, Ambiguous for more than one, and
    Unknown for none."""
    text = tidy(wanted)
    if not text:
        raise Unnamed()
    if prefix and id_of is not None:
        match = re.fullmatch(rf"{re.escape(prefix)}\s*(\d+)", text)
        if match:
            by_id = [thing for thing in things if id_of(thing) == int(match[1])]
            if by_id:
                return by_id[0]
    for found in (
        [thing for thing in things if tidy(name(thing)) == text],
        [thing for thing in things if text in tidy(name(thing))],
    ):
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise Ambiguous(wanted.strip(), found, [name(thing) for thing in found])
    raise Unknown(wanted.strip())
