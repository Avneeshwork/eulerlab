"""Special and short NSE sessions (ADR-157, research 183).

Until 2026-11-08 every downloader walked weekdays only, so no weekend session
since 2015 was held (Muhurat Sundays, Budget Saturdays, DR drills), and the
weekday Muhurat sessions that were held counted as full days in backtests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from eulerlab.ingest.kite_minute import uncovered_chunks
from eulerlab.ingest.landing import Landing
from eulerlab.ingest.nse_eod import session_days, weekend_sessions
from eulerlab.master.sessions import (
    MIN_BREADTH,
    regular_days,
    short_days,
    short_sessions,
)

FRIDAY = date(2026, 11, 6)
MUHURAT = date(2026, 11, 8)  # Sunday
MONDAY = date(2026, 11, 9)


def _land(landing: Landing, day: date, segment: str) -> None:
    landing.write(
        trade_date=day,
        segment=segment,
        file_format="udiff",
        url=f"https://example.invalid/{day}",
        payload=b"x",
        rows=1,
        inner_name="x.csv",
    )


def test_session_days_add_only_weekends_the_bhavcopy_proved(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    _land(landing, FRIDAY, "cm")
    _land(landing, MUHURAT, "cm")
    _land(landing, date(2026, 11, 7), "fo")  # an F&O file alone proves nothing
    assert weekend_sessions(tmp_path) == frozenset({MUHURAT})
    assert session_days(FRIDAY, MONDAY, tmp_path) == [FRIDAY, MUHURAT, MONDAY]


def test_with_nothing_landed_session_days_are_weekdays(tmp_path: Path) -> None:
    assert session_days(FRIDAY, MONDAY, tmp_path) == [FRIDAY, MONDAY]


def test_minute_bars_fetch_a_proved_weekend_session() -> None:
    held = [(date(2026, 10, 1), FRIDAY)]
    plain = uncovered_chunks("ACME", 1, FRIDAY, MONDAY, held)
    assert [(c.start, c.end) for c in plain] == [(MONDAY, MONDAY)]
    special = uncovered_chunks(
        "ACME", 1, FRIDAY, MONDAY, held, weekend_sessions=frozenset({MUHURAT})
    )
    assert [(c.start, c.end) for c in special] == [(MUHURAT, MONDAY)]


def _turnover(short: dict[int, float]) -> dict[date, float]:
    start = date(2026, 1, 1)
    return {start + timedelta(days=i): short.get(i, 100.0 + i % 7) for i in range(40)}


def test_a_session_far_below_its_recent_median_is_short() -> None:
    series = _turnover({30: 15.0, 35: 62.0})  # Muhurat-like, and a quiet full day
    assert short_days(series) == frozenset({date(2026, 1, 31)})


def test_early_days_without_history_are_not_judged() -> None:
    series = _turnover({3: 1.0})
    assert short_days(series) == frozenset()


@dataclass(frozen=True)
class _Row:
    day: date
    turnover: float


def test_a_narrow_panel_is_not_judged() -> None:
    days = sorted(_turnover({}))
    narrow = [_Row(d, 1.0 if d == days[30] else 100.0) for d in days]
    assert short_sessions(narrow) == frozenset()
    wide = [_Row(d, 1.0 if d == days[30] else 100.0) for d in days for _ in range(MIN_BREADTH)]
    assert short_sessions(wide) == frozenset({days[30]})


def test_regular_days_keep_the_first_decision_day() -> None:
    days = [date(2026, 11, d) for d in (2, 3, 4, 5, 6, 8, 9, 10)]
    kept, warmup = regular_days(days, 6, frozenset({MUHURAT, date(2026, 11, 3)}))
    assert MUHURAT not in kept
    assert kept[warmup] == MONDAY
    kept, warmup = regular_days(days, 5, frozenset({MUHURAT}))
    assert kept[warmup] == MONDAY  # the start was itself short: begin the next day
    assert regular_days(days, 2, frozenset()) == (days, 2)
