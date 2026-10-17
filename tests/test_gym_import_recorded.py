"""The gym import on what the real API answered (evals/fixtures/gym_import.json, recorded by `python -m
evals.gym_import --live`), for the made-up logbooks: the CSV with its DNF workout, the workbook of a tab a
workout, and the wide layout. Replayed offline, through the import's own code."""
import asyncio
import json
from pathlib import Path

import pytest

from core import grid, llm
from tasks.gym import importer
from tests import gym_files

RECORDED = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "gym_import.json").read_text(encoding="utf-8"))


def replayed(monkeypatch, name: str, tables) -> importer.Imported:
    answers = [tuple(each) if each else None for each in RECORDED[name]]

    async def call_tool(system, user, tools, **more):
        return answers.pop(0)

    monkeypatch.setattr(llm, "call_tool", call_tool)
    found = asyncio.run(importer.imported(tables))
    assert answers == [], "every recorded answer was asked for"
    return found


def test_the_logbook_csv_as_the_real_api_read_it(monkeypatch):
    found = replayed(monkeypatch, "csv", grid.from_file("logbook.csv", gym_files.logbook_csv()))
    assert [each.name for each in found.plan] == ["Upper 1", "Lower 1", "Upper 2", "Lower 2"]
    assert (len(found.sessions), found.set_count, found.not_done) == (4, 17, 1)
    notes = {note.text: note for session in found.sessions for note in session["notes"]}
    assert notes["knee felt a bit off"].pain, "a note about pain, as Claude read it"
    assert (notes["go up to 57-60kg next week"].target_low, notes["go up to 57-60kg next week"].target_high) == (57.0, 60.0)
    assert notes["too easy"].target_low is None, "a note with no target has none (the real API answered 0 for it)"
    incline = [each for each in found.sessions[0]["sets"] if each.exercise == "Incline press"]
    assert incline[0].per_hand, "a note about dumbbells: per hand"
    bench = found.plan[0].exercises[0]
    assert [each.set_type for each in bench.sets] == ["warm-up", "working", "working"] and bench.sets[1].category == "to_failure"


def test_the_workbook_of_a_tab_a_workout_as_the_real_api_read_it(monkeypatch):
    found = replayed(monkeypatch, "xlsx", grid.from_file("logbook.xlsx", gym_files.logbook_xlsx()))
    assert [each.name for each in found.plan] == ["Upper 1", "Lower 1", "Upper 2", "Lower 2"]
    assert (len(found.sessions), found.set_count, found.not_done) == (4, 17, 1)


def test_the_wide_layout_as_the_real_api_read_it(monkeypatch):
    found = replayed(monkeypatch, "wide", grid.from_file("wide.csv", gym_files.wide_csv()))
    assert [each.name for each in found.plan] == ["Push", "Pull"]
    assert [len(each.sets) for each in found.plan[0].exercises] == [3, 3]
    assert (len(found.sessions), found.set_count) == (2, 9)
