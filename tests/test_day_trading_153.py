"""Research 153: the results-gap fade (H-0040) and the expiry-day straddle (H-0041)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from eulerlab.options import expiry_straddle_screen as straddle
from eulerlab.strategies.studies import results_gap_fade as fade
from eulerlab.strategies.studies.overnight_reversal import Mark

IST = ZoneInfo("Asia/Kolkata")
SESSIONS = [date(2023, 5, 4), date(2023, 5, 5), date(2023, 5, 8)]  # Thu, Fri, Mon


def _row(symbol: str, when: str) -> dict[str, str]:
    return {"symbol": symbol, "knowledge_time": when}


def test_a_disclosure_belongs_to_the_first_session_that_opens_after_it() -> None:
    rows = [
        _row("AAA", "2023-05-04T16:10:00+05:30"),  # after Thursday's close -> Friday
        _row("BBB", "2023-05-05T08:30:00+05:30"),  # before Friday's open -> Friday
        _row("CCC", "2023-05-06T11:00:00+05:30"),  # Saturday -> Monday
        _row("DDD", "2023-05-05T11:00:00+05:30"),  # during Friday's session: not a morning
    ]
    found = fade.mornings(rows, SESSIONS)
    assert found["AAA"] == {date(2023, 5, 5): datetime.fromisoformat(rows[0]["knowledge_time"])}
    assert list(found["BBB"]) == [date(2023, 5, 5)]
    assert list(found["CCC"]) == [date(2023, 5, 8)]
    assert "DDD" not in found


def test_the_months_without_labelled_results_are_left_out() -> None:
    sessions = [date(2022, 8, 1), date(2022, 8, 2)]
    assert fade.mornings([_row("AAA", "2022-08-01T18:00:00+05:30")], sessions) == {}


def test_the_fade_trades_against_gaps_of_two_percent_or_more() -> None:
    day = date(2023, 5, 5)
    marks = {
        "UP": {day: Mark(0.03, 5, 103.0, 355, 101.0)},
        "DOWN": {day: Mark(-0.025, 5, 97.0, 355, 98.0)},
        "SMALL": {day: Mark(0.01, 5, 101.0, 355, 100.0)},
    }
    known = {s: {day: datetime(2023, 5, 4, 18, 0, tzinfo=IST)} for s in marks}
    run = fade.evaluate(marks, known, [day])
    sides = {t["symbol"]: t["side"] for t in run["trade_log"]}
    assert sides == {"UP": "short", "DOWN": "long"}
    assert run["per_trade_bps"]["gross_mean"] > 0


def test_at_most_ten_a_day_earliest_disclosure_first() -> None:
    day = date(2023, 5, 5)
    marks = {f"S{i:02d}": {day: Mark(0.05, 5, 100.0, 355, 99.0)} for i in range(12)}
    known = {s: {day: datetime(2023, 5, 4, 16, i, tzinfo=IST)} for i, s in enumerate(marks)}
    run = fade.evaluate(marks, known, [day])
    assert sorted(t["symbol"] for t in run["trade_log"]) == [f"S{i:02d}" for i in range(10)]


def _day(options: list[list[object]], d: str = "2023-05-04") -> dict[str, object]:
    return {"d": d, "opt": options}


def test_the_straddle_sells_the_strike_nearest_the_open_and_settles_at_the_close() -> None:
    index = {date(2023, 5, 4): (18_112.0, 18_160.0)}
    row = _day([[18_100.0, "CE", 60.0, 60.0, 1e6], [18_100.0, "PE", 50.0, 1.0, 1e6]])
    book, skipped = straddle.trades([row], index)
    assert not skipped
    (trade,) = book
    assert trade.strike == 18_100.0
    assert trade.payout == pytest.approx(60.0)
    # 110 received, 60 paid back: 50 points a unit before charges.
    assert trade.gross == pytest.approx(50.0 * trade.units)
    assert 0 < trade.costs < trade.gross


def test_a_day_whose_leg_did_not_trade_is_skipped_and_said() -> None:
    index = {date(2023, 5, 4): (18_100.0, 18_100.0)}
    row = _day([[18_100.0, "CE", 60.0, 60.0, 1e6], [18_100.0, "PE", None, None, 0.0]])
    book, skipped = straddle.trades([row], index)
    assert book == [] and "did not trade" in skipped[0]


def test_the_report_shows_halves_and_the_worst_days() -> None:
    index = {date(2023, 5, 4): (18_100.0, 18_400.0), date(2024, 5, 2): (22_600.0, 22_600.0)}
    rows = [
        _day([[18_100.0, "CE", 50.0, 1.0, 1.0], [18_100.0, "PE", 50.0, 1.0, 1.0]], "2023-05-04"),
        _day([[22_600.0, "CE", 60.0, 1.0, 1.0], [22_600.0, "PE", 60.0, 1.0, 1.0]], "2024-05-02"),
    ]
    book, _ = straddle.trades(rows, index)
    run = straddle.evaluate(book, [])
    assert run["net_halves"]["before_2024"]["trades"] == 1
    assert run["net_halves"]["2024"]["trades"] == 1
    assert run["worst_days"][0]["day"] == "2023-05-04"
    assert run["spent_trials"] == 0
