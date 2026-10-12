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
        # Last: every word said is a word of the name, or the start of one, in any order
        # ("evening checklist" for Evening pills checklist)
        [thing for thing in things if _all_words_fit(words(text), words(name(thing)))],
    ):
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise Ambiguous(wanted.strip(), found, [name(thing) for thing in found])
    raise Unknown(wanted.strip())


def _all_words_fit(said: list[str], of: list[str]) -> bool:
    return bool(said) and all(any(word == each or (len(word) >= 3 and each.startswith(word)) for each in of) for word in said)


# ---------------------------------------------------------------------------
# What I typed, beside what Claude handed over. Claude is told to pass a name
# on as I said it, and sometimes completes it instead ("testv" comes back as
# "Testvit" when there is a Testvit forte too), or calls it "it". So the words
# I typed are looked at as well: a part of them that fits more than one thing
# is asked about, whatever Claude made of it.
#
# A part of the message fits a thing when its words are words of the thing's
# name, in order, or the start of one (three letters or more): "testv" fits
# Testvit and Testvit forte; "it" fits neither. The longest part wins, and a
# part that is one thing's whole name means that thing.
# ---------------------------------------------------------------------------
PART_OF_A_WORD = 3  # the fewest letters that may stand for the start of a word of a name


_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _fits(said: list[str], name: list[str]) -> bool:
    """Whether the words said are words of the name, in order and together,
    each the same or (three letters or more) the start of one."""
    for start in range(len(name) - len(said) + 1):
        if all(word == of or (len(word) >= PART_OF_A_WORD and of.startswith(word)) for word, of in zip(said, name[start:])):
            return True
    return False


def said_about[T](things: Sequence[T], text: str, name: Callable[[T], str]) -> list[tuple[str, list[T]]]:
    """The parts of what was typed that name one or more of `things`: (the
    words, the things they fit), the longest part first, and no part from
    inside a longer one. A part that is one thing's whole name fits that
    thing alone."""
    typed = words(text)
    named = [(thing, words(name(thing))) for thing in things]
    taken: set[int] = set()
    found: list[tuple[str, list[T]]] = []
    for length in range(max((len(each) for _, each in named), default=0), 0, -1):
        for start in range(len(typed) - length + 1):
            span = range(start, start + length)
            if taken.intersection(span):
                continue
            part = typed[start : start + length]
            fits = [thing for thing, of in named if _fits(part, of)]
            if not fits:
                continue
            whole = [thing for thing, of in named if of == part]
            found.append((" ".join(part), whole if len(whole) == 1 else fits))
            taken.update(span)
    return found


def unclear[T](things: Sequence[T], text: str, name: Callable[[T], str], meant: T | None = None) -> Ambiguous | None:
    """What to ask, if what was typed names more than one of `things` where
    Claude handed over one (`meant`, or None for "it"): the Ambiguous to
    raise, or None when what was typed is clear or names nothing."""
    parts = said_about(things, text, name)
    if meant is not None and any(len(fits) == 1 and (fits[0] is meant or fits[0] == meant) for _, fits in parts):
        return None  # another part of what was typed names this one alone ("the evening checklist")
    for part, fits in parts:
        if len(fits) > 1 and (meant is None or any(each is meant or each == meant for each in fits)):
            return Ambiguous(part, fits, [name(each) for each in fits])
    return None
