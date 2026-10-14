"""Weather in the briefing (tasks/weather): a forecast read into a line from a template, kept so the briefing never
waits on the network, fetched and refreshed by its own schedules, and never a discord.py import."""
import asyncio
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import clock, config, database, day, design, scheduler, summaries
from tasks import weather
from tasks.weather import rules, source, store

RECORDED = Path(__file__).parent / "fixtures" / "weather_drizzle.json"


def run(coroutine):
    return asyncio.run(coroutine)


def forecast(**changes) -> dict:
    data = json.loads(RECORDED.read_text(encoding="utf-8"))
    for name, value in changes.items():
        if name == "hourly":
            data["hourly"]["precipitation_probability"] = value
        else:
            data["daily"][name] = [value]
    return data


@pytest.fixture
def on(make_db, monkeypatch, dev_clock):
    """Weather switched on, reading the recorded forecast, with a database of its own."""
    make_db({"weather": store.MIGRATIONS})
    monkeypatch.setattr(config, "WEATHER_ENABLED", True)
    monkeypatch.setattr(config, "WEATHER_SOURCE", str(RECORDED))
    told = []
    monkeypatch.setattr(summaries, "_listeners", [lambda task, user_id: told.append((task, user_id))])
    notes, reported = {}, {}
    monkeypatch.setattr(scheduler, "note", lambda job, text: notes.__setitem__(job.id, text))
    monkeypatch.setattr(scheduler, "report", lambda job, ended: reported.__setitem__(job.id, ended))
    return SimpleNamespace(told=told, notes=notes, reported=reported)


def job(number=1, local_at=None):
    return SimpleNamespace(id=number, user_id=1, task="weather", kind="fetch", local_at=local_at)


# --- the words, from a template ------------------------------------------------------------------------------------------
def test_a_recorded_forecast_reads_as_one_or_two_lines():
    found = rules.read(forecast())
    assert found == rules.Forecast(low=14, high=20, rain=61, rain_from=13, wind=15, direction="N", sky="drizzle")
    assert rules.glance(found) == "14° to 20° · drizzle" and rules.detail(found) == "61% rain after 1pm · wind 15 km/h N"


def test_rain_is_said_with_roughly_when_only_when_it_is_likely():
    dry = rules.read(forecast(precipitation_probability_max=2, weather_code=0))
    assert rules.detail(dry) == "no rain · wind 15 km/h N" and rules.glance(dry) == "14° to 20° · clear"
    slight = rules.read(forecast(precipitation_probability_max=20))
    assert rules.rain_text(slight) == "20% rain", "too unlikely to say when"
    early = rules.read(forecast(precipitation_probability_max=80, hourly=[80] * 24))
    assert rules.rain_text(early) == "80% rain from the morning"
    assert rules.rain_text(rules.read(forecast(precipitation_probability_max=60, hourly=[0] * 14 + [60] * 10))) == "60% rain after 2pm"
    assert rules.rain_text(rules.read(forecast(hourly=[]))) == "61% rain", "no hours to go by: the chance alone"


def test_the_wind_and_the_sky_are_words():
    assert [rules.compass(each) for each in (0, 44, 90, 135, 200, 225, 270, 315, 341, 359)] == ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N", "N"]
    assert [rules.sky(code) for code in (0, 2, 3, 61, 80, 95, 999)] == ["clear", "partly cloudy", "cloudy", "rain", "showers", "thunderstorms", ""]
    assert rules.hour_text(0) == "12am" and rules.hour_text(12) == "12pm" and rules.hour_text(14) == "2pm"


def test_a_forecast_that_cannot_be_read_is_refused_and_nothing_is_guessed():
    for wrong in ({}, {"daily": {}}, {"daily": {"temperature_2m_min": []}}, forecast(temperature_2m_max=None)):
        with pytest.raises(ValueError):
            rules.read(wrong)


def test_it_is_refreshed_every_three_hours_and_not_from_eight_in_the_evening():
    assert rules.later(8, 50) == [(11, 50), (14, 50), (17, 50)]
    assert rules.later(18, 0) == [] and rules.later(5, 0) == [(8, 0), (11, 0), (14, 0), (17, 0)]


# --- kept, and said through the summary contract --------------------------------------------------------------------------
def test_before_anything_is_fetched_there_is_nothing_to_say(on):
    assert run(weather.summary_for(1, day.today())) is None


def test_the_morning_fetch_keeps_the_forecast_and_the_briefing_s_section_reads_it(on):
    run(weather.fetch_job(job()))
    said = run(weather.task.summary(1, day.today()))
    assert (said.glance, said.lines, said.status) == ("14° to 20° · drizzle", ("61% rain after 1pm · wind 15 km/h N",), design.QUIET)
    assert said.hint.startswith("updated ") and on.told == [("weather", 1)], "whoever shows summaries is told: the briefing is edited in place"
    assert on.notes[1] == "fetched: 14° to 20° · drizzle · 61% rain after 1pm · wind 15 km/h N" and on.reported == {}


def test_a_failed_morning_fetch_is_a_failed_job_and_the_section_says_weather_unavailable(on, monkeypatch):
    def down():
        raise OSError("no network")

    monkeypatch.setattr(source, "_get", down)
    run(weather.fetch_job(job()))
    assert on.reported == {1: scheduler.FAILED}, "it counts as a failed job: it needs a look"
    assert on.notes[1] == "not fetched (OSError): the briefing says Weather unavailable"
    said = run(weather.summary_for(1, day.today()))
    assert said.lines == ("Weather unavailable",) and said.glance == ""


def test_a_refresh_that_fails_keeps_the_forecast_it_had_and_is_not_a_failed_job(on, monkeypatch):
    run(weather.fetch_job(job(1)))

    def down():
        raise OSError("no network")

    monkeypatch.setattr(source, "_get", down)
    run(weather.later_job(job(2)))
    assert run(weather.summary_for(1, day.today())).glance == "14° to 20° · drizzle", "the last forecast stays"
    assert on.reported == {} and on.notes[2] == "not refreshed (OSError): the last forecast stays"


def test_the_first_refresh_books_the_day_s_later_ones_once_each(on):
    clock.advance_to(day.at(day.today() + timedelta(days=1), time(8, 50)))
    today = day.today()
    run(weather.refresh_job(job(3, local_at=f"{today.isoformat()}T08:50")))
    run(weather.refresh_job(job(4, local_at=f"{today.isoformat()}T08:50")))  # asked twice: the keys make it once

    def later(conn):
        return [row[0] for row in conn.execute("SELECT due_at FROM scheduled_jobs WHERE skill = 'weather' AND kind = 'refresh_later' ORDER BY due_at")]

    due = run(database.run(later))
    assert len(due) == 3, "11:50 am, 2:50 pm and 5:50 pm, each once"
    assert on.notes[3].endswith("again every 3 hours until 8:00 pm")


def test_with_no_place_set_nothing_is_asked_and_the_reason_is_said(on, monkeypatch):
    monkeypatch.setattr(config, "WEATHER_SOURCE", "")
    monkeypatch.setattr(config, "WEATHER_LAT", None)
    run(weather.fetch_job(job()))
    assert on.notes[1] == "not fetched (WEATHER_LAT and WEATHER_LON are not set in .env): the briefing says Weather unavailable"
    monkeypatch.setattr(config, "WEATHER_LAT", -41.0)
    monkeypatch.setattr(config, "WEATHER_LON", 174.0)
    asked = source.address()
    assert asked.startswith("https://api.open-meteo.com/v1/forecast?latitude=-41.0&longitude=174.0&") and "forecast_days=1" in asked and "key" not in asked


def test_switched_off_the_task_offers_nothing(on, monkeypatch):
    run(weather.fetch_job(job()))
    monkeypatch.setattr(config, "WEATHER_ENABLED", False)
    assert weather.task.job_handlers() == {} and weather.task.job_labels() == {} and run(weather.task.summary(1, day.today())) is None


# --- how it is built --------------------------------------------------------------------------------------------------------
def test_it_is_on_the_plain_data_side_and_has_its_own_two_schedules(on, monkeypatch):
    for path in (Path(weather.__file__).parent).glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import discord" not in text and "discord_utils" not in text and "interfaces" not in text, path.name
    monkeypatch.setattr(scheduler, "_standing", {})
    weather.task.setup(None)
    made = {kind: (default.name, default.at) for (task, kind), default in scheduler.defaults().items() if task == "weather"}
    assert made == {"fetch": ("Weather fetch", time(5, 50)), "refresh": ("Weather refresh", time(8, 50))}, "both in my schedule"
    assert weather.task.actions() == [] and weather.task.entries() == [], "nothing to route to: the router never hears of it"


def test_a_task_with_a_summary_and_nothing_to_route_to_is_in_the_briefing_all_the_same(on, monkeypatch):
    from core import actions

    monkeypatch.setattr(actions, "_entries", {})
    monkeypatch.setattr(summaries, "_sources", [])
    summaries.provide("weather", weather.ICON, weather.task.summary)
    run(weather.fetch_job(job()))
    (section,) = run(summaries.gather(1, day.today()))
    assert (section.task, section.icon, section.title, section.summary.glance) == ("weather", "🌤️", "Weather", "14° to 20° · drizzle")
    from tasks.briefing import rules as briefing_rules

    lines = briefing_rules.text([section], date(2026, 10, 14)).splitlines()
    assert "🌤️ **Weather** · 14° to 20° · drizzle" in lines and "61% rain after 1pm · wind 15 km/h N" in lines, "with no change in the briefing's code"


def test_where_it_is_for_is_in_nothing_committed():
    recorded = json.loads(RECORDED.read_text(encoding="utf-8"))
    assert "latitude" not in recorded and "longitude" not in recorded
    example = (config.BASE_DIR / ".env.example").read_text(encoding="utf-8")
    assert "WEATHER_LAT=\n" in example.replace("\r\n", "\n") and "WEATHER_ENABLED=true" in example, "on by default, and no place given"
    assert datetime.now() is not None


# --- questions, answered from what was kept (DAY_QUESTIONS) ------------------------------------------------------------
def test_will_it_rain_is_the_highest_chance_in_the_hours_still_to_come_and_roughly_when():
    data = forecast()
    found = rules.read(data)
    assert rules.rain_said(data, found, "", 9) == "61% chance of rain for the rest of today, most likely between 1pm and 5pm."
    assert rules.rain_said(data, found, rules.AFTERNOON, 9) == "61% chance of rain this afternoon, most likely between 1pm and 5pm."
    assert rules.rain_said(data, found, rules.TONIGHT, 9) == "35% chance of rain tonight, most likely around 6pm."
    assert rules.rain_said(data, found, rules.MORNING_PART, 9) == "Rain is unlikely this morning: 18% at most, around 11am."
    assert rules.rain_said(data, found, rules.EVENING, 22) == "No rain expected this evening."
    assert rules.rain_said(data, found, "", 20) == "Rain is unlikely for the rest of today: 13% at most, around 8pm.", "only what is still to come"


def test_with_no_hours_in_the_forecast_only_the_day_s_own_figure_is_said_and_as_the_day_s():
    data = forecast(hourly=[10, 20])
    found = rules.read(data)
    assert rules.rain_said(data, found, rules.AFTERNOON, 9) == "61% rain today.", "no hour is made up"
    assert rules.answer(data, rules.AFTERNOON, False, 9) == ["**This afternoon**", "61% rain today.", "wind up to 15 km/h N today"]
    dry = forecast(precipitation_probability_max=2, hourly=[])
    assert rules.rain_said(dry, rules.read(dry), "", 9) == "No rain today."


def test_a_part_of_the_day_says_how_warm_only_if_the_forecast_has_it_by_the_hour():
    data = forecast()
    assert rules.answer(data, rules.AFTERNOON, False, 9) == ["**This afternoon**", "61% chance of rain this afternoon, most likely between 1pm and 5pm.", "wind up to 15 km/h N today"]
    data["hourly"]["temperature_2m"] = [14.2] * 12 + [16.6, 17.9, 19.4, 19.6, 18.8, 17.5] + [15.0] * 6
    assert rules.answer(data, rules.AFTERNOON, False, 9)[0] == "**This afternoon** · 17° to 20°"
    assert rules.answer(data, rules.TONIGHT, False, 9)[0] == "**Tonight** · 15°"
    assert rules.warmth(forecast(), (12, 18)) == ""


def test_the_day_as_a_whole_reads_as_the_briefing_s_section_and_a_part_that_is_over_says_so():
    data = forecast()
    assert rules.answer(data, "", False, 9) == ["**Today** · 14° to 20° · drizzle", "61% rain after 1pm · wind 15 km/h N"]
    assert rules.answer(data, rules.MORNING_PART, True, 13) == ["This morning is over.", "**Today** · 14° to 20° · drizzle", "61% rain after 1pm · wind 15 km/h N"]
    assert rules.answer(data, rules.TOMORROW, True, 9) == ["I only have today's forecast."]
    with pytest.raises(ValueError):
        rules.answer({"daily": {}}, "", False, 9)


def _asked(**data):
    from core.actions import Request

    return run(weather.ask(Request(SimpleNamespace(id=1), 500, "asked"), data, frozenset()))


def test_a_question_is_answered_from_the_forecast_that_was_kept_and_nothing_is_fetched(on, monkeypatch):
    monkeypatch.setattr(config, "DAY_QUESTIONS", True)
    assert _asked(rain=True) == "🌤️ I have no forecast for today yet."
    clock.advance_to(day.at(day.today() + timedelta(days=1), time(9, 0)))
    run(weather.fetch_job(job()))

    async def never():
        raise AssertionError("a question never asks the network")

    monkeypatch.setattr(source, "fetch", never)
    assert _asked(rain=True).splitlines() == ["🌤️ 61% chance of rain for the rest of today, most likely between 1pm and 5pm.", "-# updated 9:00 am"]
    assert _asked(when="afternoon").splitlines() == [
        "🌤️ **This afternoon**", "61% chance of rain this afternoon, most likely between 1pm and 5pm.", "-# wind up to 15 km/h N today · updated 9:00 am",
    ]
    assert _asked().splitlines() == ["🌤️ **Today** · 14° to 20° · drizzle", "61% rain after 1pm · wind 15 km/h N", "-# updated 9:00 am"]
    assert _asked(rain=True, when="tomorrow") == "🌤️ I only have today's forecast."
    clock.advance_to(day.at(day.today(), time(19, 0)))
    assert _asked(rain=True, when="afternoon").splitlines()[0] == "🌤️ This afternoon is over."


def test_when_the_fetch_failed_and_nothing_is_kept_it_says_unavailable_and_no_number(on, monkeypatch):
    monkeypatch.setattr(config, "DAY_QUESTIONS", True)
    monkeypatch.setattr(config, "WEATHER_SOURCE", str(RECORDED.with_name("nothing-here.json")))
    run(weather.fetch_job(job()))
    assert _asked(rain=True) == "🌤️ Weather unavailable" and not any(character.isdigit() for character in _asked())


def test_the_questions_are_one_action_with_no_card_behind_the_switch(on, monkeypatch):
    from core import actions

    assert weather.task.actions() == [] and weather.task.entries() == [], "off unless DAY_QUESTIONS is on: nothing is routed to weather"
    monkeypatch.setattr(config, "DAY_QUESTIONS", True)
    (entry,) = weather.task.entries()
    (asked,) = entry.actions
    assert (asked.name, asked.needs_card, [field.name for field in asked.fields]) == ("weather_ask", False, ["when", "rain"])
    assert actions.problems([entry]) == [] and entry.summary is not None, "it is still in the briefing, now through its entry"
    assert "rain" in entry.only_for and entry.examples[0] == "will it rain?"
    monkeypatch.setattr(config, "WEATHER_ENABLED", False)
    assert weather.task.entries() == []
    assert "temperature_2m" in source.HOURLY and "precipitation_probability" in source.HOURLY
