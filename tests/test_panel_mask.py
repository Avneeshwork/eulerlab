"""The old years' jump mask (A-146, ADR-188): built, stored, and applied by as_of."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab.backtest.strategy import MarketView
from eulerlab.features import panel_mask as pm
from eulerlab.features.panel import PanelRow, load_price_factor_store

DAYS = [date(2005, 1, 3) + timedelta(days=i) for i in range(60)]


def _series(closes: list[float]) -> list[tuple[date, float]]:
    return list(zip(DAYS, closes, strict=False))


def test_a_split_whose_jump_matches_is_kept_and_not_masked() -> None:
    closes = [100.0] * 10 + [20.5] * 10  # a 1:5 split, the market up 2.5%
    exclusions, kept, report = pm.build({"A": _series(closes)}, {"A": [(DAYS[10], 5.0)]}, DAYS)
    assert kept["A"] == [(DAYS[10], 5.0)]
    assert exclusions == [] and report.classes == {"confirmed split or bonus": 1}


def test_a_factor_with_no_matching_jump_is_dropped_and_a_late_one_kept() -> None:
    late = date(2016, 3, 1)
    _, kept, report = pm.build(
        {"A": _series([100.0] * 20)}, {"A": [(DAYS[10], 2.0), (late, 2.0)]}, DAYS
    )
    assert kept["A"] == [(late, 2.0)]  # 2015 onward is never touched
    assert (report.factors_kept, report.factors_dropped) == (0, 1)


def test_a_print_that_reverts_excludes_that_row_only() -> None:
    closes = [10.0] * 5 + [15.0] + [10.2] * 5
    exclusions, _, report = pm.build({"A": _series(closes)}, {}, DAYS)
    assert [(e.first, e.last, e.reason) for e in exclusions] == [
        (DAYS[5], DAYS[5], "one-day print")
    ]
    assert exclusions[0].known.date() == DAYS[6]  # known when it came back
    assert report.classes["one-day print, row excluded"] == 1


def test_an_unexplained_jump_masks_twenty_sessions_each_side() -> None:
    closes = [10.0] * 30 + [30.0] * 30
    exclusions, _, _ = pm.build({"A": _series(closes)}, {}, DAYS)
    (e,) = exclusions
    assert (e.first, e.last, e.reason) == (DAYS[10], DAYS[50], "unexplained jump")
    assert e.known.date() == DAYS[30]


def _row(day: date, close: float, isin: str = "A") -> PanelRow:
    return PanelRow(day=day, symbol="X", close=close, volume=1.0, turnover=1.0, isin=isin)


def test_the_mask_round_trips_and_applies_only_once_known(tmp_path: Path) -> None:
    path = tmp_path / "panel_mask.jsonl"
    exclusions, _, _ = pm.build({"A": _series([10.0] * 30 + [30.0] * 30)}, {}, DAYS)
    assert pm.write(path, exclusions) == 1
    first = json.loads(path.read_text().splitlines()[0])
    assert first["rule"] == "min_price" and first["value"] == 10.0
    mask = pm.load(path)
    assert mask is not None
    before = _row(DAYS[20], 12.0)
    assert not mask.hides(before, as_of=DAYS[25])  # the jump has not happened yet
    assert mask.hides(before, as_of=DAYS[30])
    assert not mask.hides(_row(DAYS[55], 30.0), as_of=DAYS[59])  # outside the window


def test_the_minimum_price_applies_to_2000_to_2003_only(tmp_path: Path) -> None:
    path = tmp_path / "panel_mask.jsonl"
    pm.write(path, [])
    mask = pm.load(path)
    assert mask is not None
    assert mask.hides(_row(date(2001, 5, 2), 4.0), as_of=date(2001, 5, 2))
    assert not mask.hides(_row(date(2004, 5, 3), 4.0), as_of=date(2004, 5, 3))
    assert not mask.hides(_row(date(2001, 5, 2), 12.0), as_of=date(2001, 5, 2))


def test_market_view_applies_the_mask_beside_the_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "panel_mask.jsonl"
    rows = [_row(date(2001, 5, 2), 4.0), _row(date(2001, 5, 3), 12.0)]
    monkeypatch.setattr(pm, "MASK_PATH", path)
    monkeypatch.setattr(pm.active, "__defaults__", (path,))
    assert len(MarketView(as_of=date(2001, 5, 3), history={"X": rows}).history["X"]) == 2
    pm.write(path, [])
    view = MarketView(as_of=date(2001, 5, 3), history={"X": rows})
    assert [r.close for r in view.history["X"]] == [12.0]


def test_no_mask_file_changes_nothing() -> None:
    assert pm.active(Path("/nonexistent/panel_mask.jsonl")) is None


def test_a_factor_keyed_to_an_instrument_without_an_isin_is_read(tmp_path: Path) -> None:
    path = tmp_path / "price_factors.jsonl"
    when = "2005-01-10T15:30:00+05:30"
    path.write_text(
        json.dumps(
            {"event_time": when, "knowledge_time": when, "isin": "NOISIN0123456789", "factor": 5.0}
        )
        + "\n"
    )
    records = list(load_price_factor_store(path).query(as_of=datetime(2026, 1, 1, tzinfo=UTC)))
    assert [(r.key, r.value) for r in records] == [("NOISIN0123456789", 5.0)]
