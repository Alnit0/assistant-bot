import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta

from core import database
from core.config import now_nz


@dataclass(frozen=True)
class DayStats:
    day: date
    messages: int  # chat messages sent to Claude
    commands: int
    other: int  # buttons, reactions, lab actions
    errors: int
    input_tokens: int
    output_tokens: int
    cost: float


def _daily_rows(conn, since: str) -> list[tuple]:
    # received_at is stored as NZ local time, so its first ten characters are the NZ date
    return conn.execute(
        """
        SELECT substr(received_at, 1, 10) AS day,
               SUM(kind = 'chat'),
               SUM(kind = 'command'),
               SUM(kind NOT IN ('chat', 'command')),
               SUM(status = 'error'),
               COALESCE(SUM(input_tokens), 0),
               COALESCE(SUM(output_tokens), 0),
               COALESCE(SUM(cost_usd), 0)
        FROM message_log
        WHERE substr(received_at, 1, 10) >= ?
        GROUP BY day
        ORDER BY day
        """,
        (since,),
    ).fetchall()


def fill_days(rows: list[tuple], first: date, last: date) -> list[DayStats]:
    """One entry per day from first to last, with zeros for days nothing was logged."""
    by_day = {row[0]: row[1:] for row in rows}
    stats = []
    day = first
    while day <= last:
        stats.append(DayStats(day, *by_day.get(day.isoformat(), (0, 0, 0, 0, 0, 0, 0.0))))
        day += timedelta(days=1)
    return stats


async def daily_stats(days: int) -> list[DayStats]:
    """Stats for the last `days` days in NZ time, ending today."""
    today = now_nz().date()
    first = today - timedelta(days=days - 1)
    rows = await database.run(_daily_rows, first.isoformat())
    return fill_days(rows, first, today)


def _count_today(conn, today: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM message_log WHERE kind = 'chat' AND substr(received_at, 1, 10) = ?",
        (today,),
    ).fetchone()[0]


async def messages_today() -> int:
    """Chat messages received so far today, NZ time."""
    return await database.run(_count_today, now_nz().date().isoformat())


def build_csv(stats: list[DayStats]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["date", "messages", "commands", "other", "errors", "input_tokens", "output_tokens", "cost_usd"]
    )
    for day in stats:
        writer.writerow(
            [
                day.day.isoformat(),
                day.messages,
                day.commands,
                day.other,
                day.errors,
                day.input_tokens,
                day.output_tokens,
                f"{day.cost:.6f}",
            ]
        )
    return buffer.getvalue()
