"""Unusual old-year prices: kept as published unless a bhavcopy check proves them wrong (ADR-188)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab.backtest.strategy import MarketView
from eulerlab.features import panel_mask as pm
from eulerlab.features.panel import PanelRow, load_price_factor_store

DAYS = [date(2005, 1, 3) + timedelta(days=i) for i in range(10)]


def _day(i: int, close: float, prev: float | None = None, **kw: float) -> pm.Day:
    base = {"open": close, "high": close * 1.01, "low": close * 0.99, "volume": 100.0}
    base.update(kw)
    turnover = base.pop("turnover", base["volume"] * close)
    return pm.Day(DAYS[i], close=close, turnover=turnover, prev_close=prev, **base)


def _jump(close: float, **kw: float) -> list[pm.Day]:
    """10 -> `close` on day 1, then a day whose PREVCLOSE is `close`."""
    return [_day(0, 10.0), _day(1, close, prev=10.0, **kw), _day(2, close, prev=close)]


def test_a_matching_split_is_confirmed_and_not_in_the_mask() -> None:
    rows = [_day(0, 100.0), _day(1, 20.5, prev=20.0), _day(2, 20.5, prev=20.5)]
    entries, kept, report = pm.build({"A": rows}, {"A": [(DAYS[1], 5.0)]})
    assert entries == [] and kept["A"] == [(DAYS[1], 5.0)]
    assert report.classes == {"confirmed split or bonus": 1}


def test_a_factor_that_matches_no_move_is_dropped_and_a_late_one_kept() -> None:
    late = date(2016, 3, 1)
    rows = [_day(i, 100.0) for i in range(3)]
    _, kept, report = pm.build({"A": rows}, {"A": [(DAYS[1], 2.0), (late, 2.0)]})
    assert kept["A"] == [(late, 2.0)]
    assert (report.factors_kept, report.factors_dropped) == (0, 1)


def test_a_consistent_unusual_move_stays_as_published_with_a_flag() -> None:
    entries, _, report = pm.build({"A": _jump(30.0)}, {})
    (entry,) = entries
    assert (entry.reason, entry.exclude) == (pm.UNVERIFIED, False)
    assert report.classes == {pm.UNVERIFIED: 1}


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"high": 25.0}, "open or close outside the day's range"),
        ({"turnover": 100.0}, "turnover does not match volume times a price in the range"),
    ],
)
def test_a_row_failing_its_own_checks_is_excluded(kw: dict[str, float], reason: str) -> None:
    entry, after = pm.build({"A": _jump(30.0, **kw)}, {})[0]
    assert (entry.reason, entry.exclude, entry.known.date()) == (reason, True, DAYS[1])
    # Measured from the last kept close, the next day's 30 is still unusual.
    assert (after.day, after.reason) == (DAYS[2], pm.UNVERIFIED)


def test_the_next_file_disagreeing_excludes_the_row_once_known() -> None:
    rows = [_day(0, 10.0), _day(1, 30.0, prev=10.0), _day(2, 10.1, prev=10.0)]
    (entry,) = pm.build({"A": rows}, {})[0]
    assert entry.reason == "next session's PREVCLOSE differs from this close"
    assert entry.exclude and entry.known.date() == DAYS[2]


def test_a_corporate_action_between_explains_the_next_prevclose() -> None:
    rows = [_day(0, 10.0), _day(1, 30.0, prev=10.0), _day(2, 15.0, prev=15.0)]
    entry = pm.build({"A": rows}, {}, {"A": [DAYS[2]]})[0][0]
    assert entry.day == DAYS[1] and entry.reason == pm.UNVERIFIED and not entry.exclude


def _row(day: date, close: float, isin: str = "A") -> PanelRow:
    return PanelRow(day=day, symbol="X", close=close, volume=1.0, turnover=1.0, isin=isin)


def test_the_mask_round_trips_hides_by_as_of_and_flags(tmp_path: Path) -> None:
    path = tmp_path / "panel_mask.jsonl"
    bad = [_day(0, 10.0), _day(1, 30.0, prev=10.0), _day(2, 10.1, prev=10.0)]
    entries = pm.build({"A": bad}, {})[0] + pm.build({"B": _jump(30.0)}, {})[0]
    assert pm.write(path, entries) == 2
    mask = pm.load(path)
    assert mask is not None
    assert not mask.hides(_row(DAYS[1], 30.0), as_of=DAYS[1])  # not known yet
    assert mask.hides(_row(DAYS[1], 30.0), as_of=DAYS[2])
    flagged = _row(DAYS[1], 30.0, isin="B")
    assert not mask.hides(flagged, as_of=DAYS[9]) and mask.flag(flagged) == pm.UNVERIFIED
    assert not mask.hides(_row(DAYS[1], 0.35, isin="C"), as_of=DAYS[9])  # no price floor


def test_market_view_applies_the_mask_beside_the_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "panel_mask.jsonl"
    rows = [_row(DAYS[0], 10.0), _row(DAYS[1], 30.0), _row(DAYS[2], 10.1)]
    monkeypatch.setattr(pm.active, "__defaults__", (path,))
    assert len(MarketView(as_of=DAYS[2], history={"X": rows}).history["X"]) == 3
    bad = [_day(0, 10.0), _day(1, 30.0, prev=10.0), _day(2, 10.1, prev=10.0)]
    pm.write(path, pm.build({"A": bad}, {})[0])
    early = MarketView(as_of=DAYS[1], history={"X": rows[:2]})
    assert len(early.history["X"]) == 2
    late = MarketView(as_of=DAYS[2], history={"X": rows})
    assert [r.day for r in late.history["X"]] == [DAYS[0], DAYS[2]]


def test_no_mask_file_changes_nothing() -> None:
    assert pm.active(Path("/nonexistent/panel_mask.jsonl")) is None


def test_a_factor_keyed_to_an_instrument_without_an_isin_is_read(tmp_path: Path) -> None:
    path = tmp_path / "price_factors.jsonl"
    when = "2005-01-10T15:30:00+05:30"
    row = {"event_time": when, "knowledge_time": when, "isin": "NOISIN0123456789", "factor": 5.0}
    path.write_text(json.dumps(row) + "\n")
    records = list(load_price_factor_store(path).query(as_of=datetime(2026, 1, 1, tzinfo=UTC)))
    assert [(r.key, r.value) for r in records] == [("NOISIN0123456789", 5.0)]
