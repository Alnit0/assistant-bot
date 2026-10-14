"""A task behind a switch that is off is not loaded: not in help, #commands or the router (tasks/base.py, `switched_on`)."""
from types import SimpleNamespace

import pytest

from core import actions
from tasks import registry
from tasks.builtin import build_overview, commands
from tasks.schedule import task as schedule_task


@pytest.fixture
def loaded():
    registry.load()
    yield
    registry.load()


def _help() -> str:
    return build_overview(SimpleNamespace(user=None, channel_id=None))


def test_a_task_switched_on_is_in_help_and_the_router(loaded):
    assert "schedule" in [task.name for task in registry.loaded_tasks()]
    assert "schedule" in _help().lower() and actions.entry("schedule") is not None


def test_a_task_switched_off_is_out_of_help_commands_and_the_router(loaded, monkeypatch):
    monkeypatch.setattr(type(schedule_task), "switched_on", lambda self: False)
    registry.load()
    assert "schedule" not in [task.name for task in registry.loaded_tasks()]
    assert "my schedule" not in _help() and registry.find("schedule") is None
    assert all(entry.name != "schedule" for entry in actions.catalogue()), "the router is not offered it"
    assert "my schedule" not in "\n".join(commands.pages()), "#commands does not list it"
    assert not registry.problems(), "an off task is not a problem"
