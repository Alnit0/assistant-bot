import re
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Keyword router
#
# Decides whether a message is one of the registered words or phrases (such as
# "stats" or "lab chart") rather than something to chat about. Pure text
# matching: it knows nothing about Discord or skills.
#
# The rules, chosen so ordinary chat is never mistaken for a command:
# - The whole message must be the phrase. Extra words are only accepted for
#   entries registered with takes_args, and then become the arguments.
# - Small typos are forgiven: one wrong, missing, extra or swapped letter per
#   word, but only in words of FUZZY_MIN_LENGTH letters or more, and only when
#   exactly one entry fits.
# - Entries registered as exact are never matched by a typo.
# ---------------------------------------------------------------------------
FUZZY_MIN_LENGTH = 5


def normalise(text: str) -> list[str]:
    """Lower-case words, ignoring extra spaces and punctuation at the end."""
    return text.strip().rstrip(".!?").lower().split()


def within_one_edit(typed: str, real: str) -> bool:
    """True if one changed, missing, extra or swapped letter turns `typed` into `real`."""
    if typed == real:
        return True
    if abs(len(typed) - len(real)) > 1:
        return False

    # Skip what the two words have in common at the start
    start = 0
    while start < min(len(typed), len(real)) and typed[start] == real[start]:
        start += 1
    rest_typed, rest_real = typed[start:], real[start:]

    if len(rest_typed) == len(rest_real):
        # One letter changed, or two neighbours swapped
        return rest_typed[1:] == rest_real[1:] or (
            len(rest_typed) >= 2
            and rest_typed[0] == rest_real[1]
            and rest_typed[1] == rest_real[0]
            and rest_typed[2:] == rest_real[2:]
        )
    if len(rest_typed) > len(rest_real):
        return rest_typed[1:] == rest_real  # one extra letter
    return rest_typed == rest_real[1:]  # one missing letter


def _word_matches(typed: str, real: str, allow_typo: bool) -> bool | None:
    """True for an exact match, False for a forgiven typo, None for no match."""
    if typed == real:
        return True
    if (
        allow_typo
        and len(typed) >= FUZZY_MIN_LENGTH
        and len(real) >= FUZZY_MIN_LENGTH
        and within_one_edit(typed, real)
    ):
        return False
    return None


@dataclass(frozen=True)
class Match:
    entry: Any  # whatever was registered for the phrase
    phrase: str  # the registered phrase that matched, e.g. "lab chart"
    args: list[str]  # the words after the phrase
    corrected: bool  # True if a typo was forgiven to get here


@dataclass(frozen=True)
class _Route:
    words: tuple[str, ...]
    entry: Any
    takes_args: bool
    exact: bool


class Router:
    def __init__(self):
        self._routes: list[_Route] = []
        self._patterns: list[tuple[re.Pattern[str], Any]] = []

    def add_pattern(self, pattern: str, entry: Any) -> None:
        """Register a regular expression for inputs that aren't fixed words, e.g. "+10m".

        It must match the whole (normalised) message. What its groups capture
        becomes the arguments. Words are tried first, and patterns are never
        matched by typo.
        """
        self._patterns.append((re.compile(pattern), entry))

    def owner(self, phrase: str) -> Any | None:
        """The entry already registered for this phrase, if any."""
        words = tuple(normalise(phrase))
        for route in self._routes:
            if route.words == words:
                return route.entry
        return None

    def add(self, phrase: str, entry: Any, *, takes_args: bool = False, exact: bool = False) -> None:
        words = tuple(normalise(phrase))
        if not words:
            raise ValueError("a phrase needs at least one word")
        if self.owner(phrase) is not None:
            raise ValueError(f"`{phrase}` is already registered")
        self._routes.append(_Route(words, entry, takes_args, exact))

    def phrases(self) -> list[str]:
        return [" ".join(route.words) for route in self._routes]

    def match(self, text: str) -> Match | None:
        typed = normalise(text)
        if not typed:
            return None
        # Matching ignores case, but arguments keep theirs ("timer 5m Roast chicken")
        original = text.strip().rstrip(".!?").split()

        exact_matches: list[_Route] = []
        typo_matches: list[_Route] = []
        for route in self._routes:
            length = len(route.words)
            if len(typed) < length or (len(typed) > length and not route.takes_args):
                continue
            results = [
                _word_matches(typed_word, real_word, allow_typo=not route.exact)
                for typed_word, real_word in zip(typed, route.words)
            ]
            if None in results:
                continue
            (exact_matches if all(results) else typo_matches).append(route)

        # The longest phrase wins: "lab chart" beats a "lab" that takes arguments
        if exact_matches:
            route = max(exact_matches, key=lambda r: len(r.words))
            return Match(route.entry, " ".join(route.words), original[len(route.words) :], False)

        if typo_matches:
            longest = max(len(route.words) for route in typo_matches)
            candidates = [route for route in typo_matches if len(route.words) == longest]
            # Two different things it could have been: don't guess
            if len({id(route.entry) for route in candidates}) == 1:
                route = candidates[0]
                return Match(route.entry, " ".join(route.words), original[longest:], True)
            return None

        text = " ".join(typed)
        for pattern, entry in self._patterns:
            found = pattern.fullmatch(text)
            if found is not None:
                args = " ".join(group for group in found.groups() if group).split()
                return Match(entry, text, args, False)
        return None
