from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# An animated grid, as a proof of concept (Alex, 21 Oct: "let's get a basic
# command that displays something"): a 5 by 5 grid of square emoji, the same
# message edited frame by frame. Behind LAB_GRID (off). The real use to follow
# is a progress grid that fills while the bot works on something slow, then
# becomes the answer.
#
# Pure: the frames, the seconds between them, the one-at-a-time lock and the
# measurements. The edits themselves are tasks/lab/animate.py, through the door.
#
#   frame 0     every square ⬛, posted at once
#   frames 1-8  a diagonal rainbow wave: row r, column c is
#               PALETTE[(r + c + frame) % 6], so the colours roll across
#   frame 9     every square 🟩: it has settled, and stops for good
# ---------------------------------------------------------------------------
SIZE = 5
PALETTE = ("🟥", "🟧", "🟨", "🟩", "🟦", "🟪")
BLACK, GREEN = "⬛", "🟩"
# An invisible first line (a zero-width space): with Discord's Compact display the message's first line sits
# beside the bot's name, so the grid's first row starts on the line below it (Alex, 21 Oct, on his PC)
FIRST_LINE = "​"
WAVES = 8  # frames 1 to 8
LAST = WAVES + 1  # frame 9, the settle
SECONDS, FASTEST, SLOWEST = 1.0, 0.5, 3.0  # between frames: the default, and how far it may go each way


def squares(frame: int) -> list[str]:
    """The 25 squares of a frame, row by row."""
    if frame <= 0:
        return [BLACK] * (SIZE * SIZE)
    if frame >= LAST:
        return [GREEN] * (SIZE * SIZE)
    return [PALETTE[(row + column + frame) % len(PALETTE)] for row in range(SIZE) for column in range(SIZE)]


def frame_text(frame: int) -> str:
    """A frame as the message's whole text: an invisible first line, then five rows of five squares and nothing else."""
    found = squares(frame)
    return "\n".join([FIRST_LINE, *("".join(found[row * SIZE:(row + 1) * SIZE]) for row in range(SIZE))])


def seconds(said: str | None) -> float:
    """The seconds between frames, from what was typed after "lab grid": 1.0 when nothing (or no number) is said,
    and never under FASTEST or over SLOWEST."""
    try:
        value = float(str(said).strip()) if said is not None and str(said).strip() else SECONDS
    except ValueError:
        return SECONDS
    if value != value:  # nan
        return SECONDS
    return max(FASTEST, min(SLOWEST, value))


class OneAtATime:
    """Never more than one grid running across the whole bot."""

    def __init__(self) -> None:
        self.running = False

    def take(self) -> bool:
        """True if this one may run (and now holds it); False while another runs."""
        if self.running:
            return False
        self.running = True
        return True

    def release(self) -> None:
        self.running = False


@dataclass
class Run:
    """One run's measurements, for the log: the gap a person sees between frames (one edit returning to the next
    returning; the first from the post returning), and the edits that were rate-limited or failed."""

    seconds: float
    gaps: list[float] = field(default_factory=list)
    limited: int = 0
    failed: int = 0
    frames: int = 1  # frame 0 is up once the post returns

    @property
    def average(self) -> float:
        return sum(self.gaps) / len(self.gaps) if self.gaps else 0.0

    @property
    def slowest(self) -> float:
        return max(self.gaps) if self.gaps else 0.0

    @property
    def finished(self) -> bool:
        return self.frames == LAST + 1

    def line(self) -> str:
        return (
            f"lab grid at {self.seconds:.1f}s: {self.frames} of {LAST + 1} frames, gap {self.average:.2f}s on average, "
            f"{self.slowest:.2f}s at most; {self.limited} rate-limited, {self.failed} failed"
            + ("" if self.finished else "; stopped early, left as it was")
        )
