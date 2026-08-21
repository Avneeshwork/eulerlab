"""The full backtest report, and the two things it must never do quietly.

It must not present an attribution that does not add up, and it must not
present a Sharpe from a mostly-idle run as though it were comparable to one
from a fully-invested run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab import reports
from eulerlab import workspace as ws
from eulerlab.costs.schedule import Side


@dataclass(frozen=True)
class _Fill:
    day: date
    symbol: str
    side: Side
    quantity: int
    price: float
    cost: float


@pytest.fixture()
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ws.Workspace:
    monkeypatch.setattr(ws, "ROOT", tmp_path / "workspaces")
    return ws.Workspace(id="tenant-a").ensure()


def _days(n: int) -> list[date]:
    start = date(2026, 1, 1)
    return [start + timedelta(days=i) for i in range(n)]


# --- attribution -----------------------------------------------------------


def test_a_round_trip_attributes_its_profit_to_the_instrument() -> None:
    fills = [
        _Fill(date(2026, 1, 2), "AAA", Side.BUY, 100, 10.0, 5.0),
        _Fill(date(2026, 1, 9), "AAA", Side.SELL, 100, 12.0, 5.0),
    ]
    payload = reports.build(
        strategy_id="demo",
        configuration="cfg",
        universe="all",
        instruments=[],
        tier="B",
        window_days=10,
        equity=[1000.0, 1190.0],
        days=_days(2),
        fills=fills,
        rejections=[],
        marks={},
        starting_cash=1000.0,
    )
    row = payload["constituents"][0]
    # Bought 1,000, sold 1,200, paid 10 in costs.
    assert row["contribution"] == 190.0
    assert payload["reconciliation"]["exact"] is True


def test_an_open_position_is_marked_not_dropped() -> None:
    """Dropping it would make the attribution reconcile by discarding the thing
    that broke it."""
    fills = [_Fill(date(2026, 1, 2), "AAA", Side.BUY, 100, 10.0, 0.0)]
    payload = reports.build(
        strategy_id="demo",
        configuration="cfg",
        universe="all",
        instruments=[],
        tier="B",
        window_days=10,
        equity=[1000.0, 1200.0],
        days=_days(2),
        fills=fills,
        rejections=[],
        marks={"AAA": 12.0},
        starting_cash=1000.0,
    )
    row = payload["constituents"][0]
    assert row["open_qty"] == 100
    assert row["open_value"] == 1200.0
    assert row["contribution"] == 200.0


def test_a_residual_is_reported_not_absorbed() -> None:
    """An attribution that silently does not add up is worse than none: it
    invites the reader to trust a decomposition that is wrong."""
    fills = [_Fill(date(2026, 1, 2), "AAA", Side.BUY, 100, 10.0, 0.0)]
    payload = reports.build(
        strategy_id="demo",
        configuration="cfg",
        universe="all",
        instruments=[],
        tier="B",
        window_days=10,
        # Equity says +500 but the fills only explain -1000 + 1000 = 0.
        equity=[1000.0, 1500.0],
        days=_days(2),
        fills=fills,
        rejections=[],
        marks={"AAA": 10.0},
        starting_cash=1000.0,
    )
    reconciliation = payload["reconciliation"]
    assert reconciliation["exact"] is False
    assert reconciliation["residual"] == 500.0


def test_a_symbol_with_no_mark_is_named() -> None:
    fills = [_Fill(date(2026, 1, 2), "AAA", Side.BUY, 100, 10.0, 0.0)]
    payload = reports.build(
        strategy_id="demo",
        configuration="cfg",
        universe="all",
        instruments=[],
        tier="B",
        window_days=10,
        equity=[1000.0, 1000.0],
        days=_days(2),
        fills=fills,
        rejections=[],
        marks={},
        starting_cash=1000.0,
    )
    assert payload["reconciliation"]["unmarked_symbols"] == ["AAA"]


# --- the idle-run warning --------------------------------------------------


def test_a_mostly_flat_run_is_flagged() -> None:
    """This is not hypothetical. momentum_12_1 on nifty50 requires min_names=50
    against a 50-name universe, so one instrument short of history blocks every
    trade. It held cash for three of four years and still reported Sharpe 0.27,
    which reads as a weak result rather than as an absent one.
    """
    equity = [1000.0] * 80 + [1000.0 + i for i in range(20)]
    payload = reports.build(
        strategy_id="demo",
        configuration="cfg",
        universe="nifty50",
        instruments=[],
        tier="B",
        window_days=100,
        equity=equity,
        days=_days(len(equity)),
        fills=[],
        rejections=[],
        marks={},
        starting_cash=1000.0,
    )
    assert payload["metrics"]["invested_fraction"] < 0.5
    assert any("held nothing for most of this run" in w for w in payload["warnings"])
    assert payload["metrics"]["first_move_day"] is not None


def test_a_fully_invested_run_is_not_flagged() -> None:
    equity = [1000.0 * (1.001**i) for i in range(120)]
    payload = reports.build(
        strategy_id="demo",
        configuration="cfg",
        universe="all",
        instruments=[],
        tier="B",
        window_days=120,
        equity=equity,
        days=_days(120),
        fills=[],
        rejections=[],
        marks={},
        starting_cash=1000.0,
    )
    assert payload["metrics"]["invested_fraction"] == 1.0
    assert not any("held nothing" in w for w in payload["warnings"])


def test_hit_rate_is_offered_over_invested_days_too() -> None:
    """The plain hit rate counts flat days as misses, which explains nothing."""
    equity = [1000.0] * 50 + [1000.0 + i for i in range(1, 51)]
    payload = reports.build(
        strategy_id="demo",
        configuration="cfg",
        universe="all",
        instruments=[],
        tier="B",
        window_days=100,
        equity=equity,
        days=_days(len(equity)),
        fills=[],
        rejections=[],
        marks={},
        starting_cash=1000.0,
    )
    metrics = payload["metrics"]
    assert metrics["hit_rate"] < metrics["hit_rate_invested"]


# --- storage ---------------------------------------------------------------


def test_a_report_round_trips(space: ws.Workspace) -> None:
    payload = {"strategy_id": "demo", "configuration": "cfg", "metrics": {}}
    reports.save(space, payload)
    assert reports.load(space, "demo", "cfg") == payload


def test_a_missing_report_is_none_not_an_error(space: ws.Workspace) -> None:
    assert reports.load(space, "demo", "never") is None


def test_reports_do_not_leak_between_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ws, "ROOT", tmp_path / "workspaces")
    a = ws.Workspace(id="tenant-a").ensure()
    b = ws.Workspace(id="tenant-b").ensure()
    reports.save(a, {"strategy_id": "demo", "configuration": "cfg"})
    assert reports.load(b, "demo", "cfg") is None
