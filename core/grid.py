import csv
import io
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# A grid from a file or pasted rows: headings and rows, knowing nothing of any
# task (the gym imports its logbook with it, the smart inbox reads a table). Blank
# rows are kept as blank, since a logbook's blank rows part its workouts.
# ---------------------------------------------------------------------------
MAX_ROWS = 2000
MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Table:
    name: str  # the file's, or the tab's ("Upper 1"): one tab a workout is read from it
    headings: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]  # under the headings; a blank row is all ""

    def column(self, index: int) -> list[str]:
        return [row[index] if index < len(row) else "" for row in self.rows]

    def samples(self, count: int = 3) -> list[tuple[str, ...]]:
        return [row for row in self.rows if any(row)][:count]


def _cells(row) -> tuple[str, ...]:
    return tuple("" if cell is None else (f"{cell:g}" if isinstance(cell, float) else str(cell)).strip() for cell in row)


def _from_rows(name: str, rows: list[tuple[str, ...]]) -> Table | None:
    """The first row with text in two or more cells is the headings; everything under it the rows."""
    for index, row in enumerate(rows):
        if sum(1 for cell in row if cell) >= 2:
            width = max(len(each) for each in rows[index:]) if rows[index:] else len(row)
            pad = lambda each: tuple(each) + ("",) * (width - len(each))
            body = [pad(each) for each in rows[index + 1:]][:MAX_ROWS]
            while body and not any(body[-1]):
                body.pop()
            return Table(name, pad(row), tuple(body))
    return None


def from_csv(name: str, data: bytes) -> list[Table]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return from_text(name, text)


def from_text(name: str, text: str) -> list[Table]:
    """Pasted rows: tab, comma or semicolon apart (whichever the first lines use most)."""
    lines = [line for line in str(text or "").replace("\r\n", "\n").split("\n")]
    sample = "\n".join(lines[:5])
    delimiter = max(("\t", ",", ";"), key=sample.count)
    if sample.count(delimiter) == 0:
        return []
    rows = [_cells(row) for row in csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)]
    found = _from_rows(name, rows)
    return [found] if found is not None else []


def from_xlsx(name: str, data: bytes) -> list[Table]:
    """Every tab with a table on it, each a table named by its tab."""
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    found = []
    for sheet in book.worksheets:
        rows = [_cells(row) for row in sheet.iter_rows(values_only=True)]
        table = _from_rows(sheet.title, rows)
        if table is not None:
            found.append(table)
    book.close()
    return found


def from_file(name: str, data: bytes) -> list[Table]:
    if len(data) > MAX_BYTES:
        return []
    if name.lower().endswith(".xlsx"):
        return from_xlsx(name, data)
    return from_csv(name, data)


_TABLE_LIKE = re.compile(r"[\t,;]")


def looks_like_rows(text: str) -> bool:
    """Whether pasted words hold a table: two lines or more, each with a separator."""
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return len(lines) >= 2 and all(_TABLE_LIKE.search(line) for line in lines[:3])
