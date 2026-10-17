"""The gym import's two requests against the real API (the columns' mapping, and what the logbook's words mean),
on the made-up logbooks of tests/gym_files.py, recorded for tests/test_gym_import_recorded.py to replay.

    python -m evals.gym_import             say what it would ask
    python -m evals.gym_import --live      ask the real API (a few cents) and record what came back

Nothing here reads or writes a database, and no real logbook is ever used.
"""
import asyncio
import json
import sys
from pathlib import Path

RECORDED = Path(__file__).resolve().parent / "fixtures" / "gym_import.json"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    from core import grid, llm
    from tasks.gym import importer
    from tests import gym_files

    files = {"csv": grid.from_file("logbook.csv", gym_files.logbook_csv()), "xlsx": grid.from_file("logbook.xlsx", gym_files.logbook_xlsx()), "wide": grid.from_file("wide.csv", gym_files.wide_csv())}
    if "--live" not in sys.argv:
        print(f"{len(files)} logbooks, 2 requests each, roughly US$0.03. Add --live to run it.")
        return 0
    recorded = {}
    real = llm.call_tool

    async def one(name, tables):
        answers = []

        async def keep(system, user, tools, **more):
            found = await real(system, user, tools, **more)
            answers.append([found[0], found[1]] if found else None)
            return found

        llm.call_tool = keep
        try:
            result = await importer.imported(tables)
        finally:
            llm.call_tool = real
        recorded[name] = answers
        print(f"{name}: {len(result.plan)} workouts ({', '.join(each.name for each in result.plan)}), {len(result.sessions)} sessions, {result.set_count} sets, "
              f"{result.not_done} not done, unsure {result.unsure}, unused {result.unused}")

    async def all_of():
        for name, tables in files.items():
            await one(name, tables)

    asyncio.run(all_of())
    RECORDED.write_text(json.dumps(recorded, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Recorded into {RECORDED.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
