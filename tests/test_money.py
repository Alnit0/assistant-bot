"""Money as I see it (core/money.py): NZ$ shown, US$ recorded, the rate fetched once a day with the last known one
or the setting behind it, the limits in round NZ$, and the briefing's spend line."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import config, costs, database, health, money, scheduler
from tasks.briefing import rules as briefing_rules


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture(autouse=True)
def rate(monkeypatch):
    """No rate fetched yet, and the setting at its default of 1.70."""
    monkeypatch.setattr(money, "_rate", None)
    monkeypatch.setattr(config, "USD_TO_NZD", 1.70)


def test_what_i_read_is_nz_dollars_and_what_is_recorded_stays_us_dollars():
    assert money.shown(0.25) == "NZ$0.42" and money.shown(0.1234, 4) == "NZ$0.2098" and money.shown(None) == "unknown"
    assert costs.money(0.25) == "NZ$0.4250", "dev cost, a ping, the briefing, the status line"
    assert costs.usd(0.25) == "US$0.2500", "the record, as billed"
    assert round(money.usd(money.nzd(3.21)), 9) == 3.21


def test_with_nothing_fetched_the_setting_is_the_rate_and_dev_cost_says_so(monkeypatch):
    assert money.current() == money.Rate(1.70) and money.said() == "US$1 = NZ$1.7000 (USD_TO_NZD in .env: no rate has been fetched yet)"
    assert "USD_TO_NZD=1.70" in (config.BASE_DIR / ".env.example").read_text(encoding="utf-8")
    monkeypatch.setattr(money, "_rate", money.Rate(1.7859, datetime(2026, 10, 13, 16, 30, tzinfo=timezone.utc)))
    assert money.said() == "US$1 = NZ$1.7859 (Frankfurter (ECB), fetched 14 Oct at 5:30 am)", "which rate, and from when"
    assert costs.report(costs.Period(), costs.Period(), [], "assistant.db").splitlines()[-1] == "-# Shown in NZ$, recorded in US$: " + money.said()


def test_the_answer_is_read_and_one_that_is_missing_or_absurd_is_refused():
    assert money.read(b'{"amount":1.0,"base":"USD","date":"2026-10-12","rates":{"NZD":1.7859}}') == 1.7859
    for wrong in (b'{"rates":{}}', b'not json', b'{"rates":{"NZD":"x"}}', b'{"rates":{"NZD":170}}', b'{"rates":{"NZD":0}}'):
        with pytest.raises(ValueError):
            money.read(wrong)


def test_a_fetch_is_kept_and_a_failed_one_leaves_the_last_known_rate_in_use_without_being_a_failed_job(db, monkeypatch):
    notes, reported = [], []
    monkeypatch.setattr(scheduler, "note", lambda job, text: notes.append(text))
    monkeypatch.setattr(scheduler, "report", lambda job, outcome: reported.append(outcome))
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    monkeypatch.setattr(money, "_get", lambda: b'{"rates":{"NZD":1.7859}}')
    run(money.fetch_job(SimpleNamespace(id=1)))
    assert money.current().value == 1.7859 and notes == ["fetched: US$1 = NZ$1.7859"]

    def down():
        raise OSError("no network")

    monkeypatch.setattr(money, "_get", down)
    run(money.fetch_job(SimpleNamespace(id=2)))
    assert money.current().value == 1.7859, "the last known rate"
    assert notes[-1].startswith("could not be fetched (OSError): US$1 = NZ$1.7859") and reported == [], "said in the run's line, and nobody is pinged for it"
    # After a restart the last one fetched is taken up again
    monkeypatch.setattr(money, "_rate", None)
    assert run(money.load()).value == 1.7859
    assert money.load_from(database.DB_PATH).value == 1.7859, "and by the self-test's launcher, which reads live's database"
    assert money.load_from("nowhere.db") == money.Rate(1.70), "none to read: the setting"


def test_the_dev_bot_never_fetches(db, monkeypatch):
    notes = []
    monkeypatch.setattr(scheduler, "note", lambda job, text: notes.append(text))
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    monkeypatch.setattr(money, "_get", lambda: pytest.fail("the dev bot asked the network"))
    run(money.fetch_job(SimpleNamespace(id=1)))
    assert notes[0].startswith("not fetched: the dev bot uses what it has")
    assert money.DEFAULT.locked and money.DEFAULT.name == "Exchange rate", "a job of the bot's own, in my schedule"


def test_the_limits_are_round_nz_dollars_compared_in_us_dollars_at_the_rate_of_the_moment(monkeypatch):
    text = (config.BASE_DIR / ".env.example").read_text(encoding="utf-8")
    assert "DAILY_SPEND_LIMIT_NZD=1.00" in text and "SELFTEST_MONTHLY_LIMIT_NZD=3.50" in text
    assert "DAILY_SPEND_LIMIT=" not in text and "SELFTEST_MONTHLY_LIMIT=" not in text, "renamed, not both"
    monkeypatch.setattr(config, "DAILY_SPEND_LIMIT_NZD", 1.00)
    monkeypatch.setattr(config, "SELFTEST_MONTHLY_LIMIT_NZD", 3.50)
    assert round(costs.daily_limit(), 4) == 0.5882 and round(health.selftest_limit(), 4) == 2.0588
    assert costs.limit_money(costs.daily_limit()) == "NZ$1.00" and costs.limit_line(0.70, costs.daily_limit()) == "-# ⚠️ over today's limit: NZ$1.1900 of NZ$1.00 (DAILY_SPEND_LIMIT_NZD)"
    assert health.spend_problem(2.5, health.selftest_limit()).short == ("self-test spend", "NZ$4.25"), "the status line too"


def test_the_briefing_s_spend_line_hides_the_amounts_and_is_left_out_for_a_day_with_no_spend(db, monkeypatch, tmp_path):
    assert briefing_rules.spend_line("NZ$0.12", "NZ$0.30", "NZ$0.42") == "💸 Yesterday: ||NZ$0.42 · you NZ$0.12 · testing NZ$0.30||"
    day = date(2026, 10, 13)
    folder = tmp_path / "selftest"
    folder.mkdir()
    (folder / "history.csv").write_text("date,spend_usd\n2026-10-13 22:51,0.1652\n2026-10-13 23:12,0.1656\n2026-10-12 20:00,0.5\n", encoding="utf-8")
    assert round(health.day_spend(health.history(folder), day), 4) == 0.3308 and health.day_spend([], day) == 0.0
    from tasks import briefing

    async def spent(on):
        return (0.07, 0.19) if on == day else (0.0, 0.0)

    monkeypatch.setattr(health, "spent_on", spent)
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    assert run(briefing.spend_line(day + timedelta(days=1))) == "💸 Yesterday: ||NZ$0.44 · you NZ$0.12 · testing NZ$0.32||"
    assert run(briefing.spend_line(day)) == "", "a day with no spend: no line"
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    assert run(briefing.spend_line(day + timedelta(days=1))) == "", "the dev bot's briefing has no money in it"
    assert "💸 Yesterday: ||x||" in briefing_rules.text([], day, spend="💸 Yesterday: ||x||").splitlines()
