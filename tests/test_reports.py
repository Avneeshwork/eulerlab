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
    loaded = reports.load(space, "demo", "cfg")
    assert loaded is not None
    assert {k: v for k, v in loaded.items() if k != "provenance"} == payload


def test_a_rerun_keeps_the_report_it_supersedes(space: ws.Workspace) -> None:
    """The bug this fixes: one file per configuration, replaced on a re-run."""
    first = reports.save(space, {"strategy_id": "demo", "configuration": "cfg", "n": 1})
    second = reports.save(space, {"strategy_id": "demo", "configuration": "cfg", "n": 2})
    assert first != second
    assert first.exists() and second.exists()

    latest = reports.load(space, "demo", "cfg")
    assert latest is not None and latest["n"] == 2

    history = reports.history(space, "demo", "cfg")
    assert [entry["run_id"] for entry in history] == [first.stem, second.stem]
    earlier = reports.load(space, "demo", "cfg", first.stem)
    assert earlier is not None and earlier["n"] == 1


def test_a_saved_report_names_the_code_that_produced_it(space: ws.Workspace) -> None:
    reports.save(space, {"strategy_id": "demo", "configuration": "cfg"})
    loaded = reports.load(space, "demo", "cfg")
    assert loaded is not None
    provenance = loaded["provenance"]
    assert provenance["run_id"]
    assert provenance["recorded_at"]
    assert set(provenance["code"]) == {"commit", "dirty", "dirty_paths"}
    assert provenance["cost_model"]


def test_a_stored_run_is_never_overwritten(space: ws.Workspace) -> None:
    payload = {"strategy_id": "demo", "configuration": "cfg"}
    path = reports.save(space, payload)
    stored = reports.load(space, "demo", "cfg")
    assert stored is not None
    with pytest.raises(FileExistsError):
        reports.save(space, stored)  # same provenance, same run id
    assert path.exists()


def test_a_report_written_before_run_ids_still_loads(space: ws.Workspace) -> None:
    legacy = space.root / "reports" / "demo" / "cfg.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"strategy_id": "demo", "configuration": "cfg"}', encoding="utf-8")
    assert reports.load(space, "demo", "cfg") == {"strategy_id": "demo", "configuration": "cfg"}
    assert reports.history(space, "demo", "cfg") == []


@pytest.mark.parametrize("bad", ["../../etc", "a/b", ".hidden", "a\\b"])
def test_a_name_that_leaves_the_folder_is_refused(space: ws.Workspace, bad: str) -> None:
    reports.save(space, {"strategy_id": "demo", "configuration": "cfg"})
    assert reports.load(space, "demo", "cfg", bad) is None
    assert reports.load(space, "demo", bad) is None
    assert reports.history(space, "demo", bad) == []


def test_a_built_report_carries_its_trades_and_parameters() -> None:
    fills = [
        _Fill(date(2026, 1, 2), "AAA", Side.BUY, 100, 10.0, 5.0),
        _Fill(date(2026, 1, 9), "AAA", Side.SELL, 100, 12.0, 5.0),
    ]
    payload = reports.build(
        strategy_id="demo",
        configuration="cfg",
        universe="custom",
        instruments=["AAA"],
        tier="B",
        window_days=10,
        equity=[1000.0, 1000.0, 1190.0],
        days=_days(3),
        fills=fills,
        rejections=[],
        marks={},
        starting_cash=1000.0,
        params={"lookback": 20},
        data_version="v1",
    )
    assert payload["params"] == {"lookback": 20}
    assert payload["data_version"] == "v1"
    assert len(payload["trades"]) == 1
    assert payload["trades"][0]["net"] == 190.0
    assert payload["trade_summary"]["wins"] == 1


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


def test_pruning_a_configuration_drops_its_history_too(space: ws.Workspace) -> None:
    from eulerlab.prune_runs import _drop_reports

    kept = reports.save(space, {"strategy_id": "demo", "configuration": "keep"})
    dropped = reports.save(space, {"strategy_id": "demo", "configuration": "drop"})
    _drop_reports(space, "demo", keep="keep")
    assert kept.exists()
    assert not dropped.exists()
    assert reports.load(space, "demo", "drop") is None


def test_total_return_is_measured_from_the_starting_cash() -> None:
    """The first day's close is already net of that day's costs. Measured from
    it, a report read 58.87% beside a rupee gain of 58.77% (T-4345)."""
    fills = [_Fill(date(2026, 1, 1), "AAA", Side.BUY, 100, 10.0, 6.0)]
    payload = reports.build(
        strategy_id="demo",
        configuration="cfg",
        universe="all",
        instruments=[],
        tier="B",
        window_days=10,
        equity=[994.0, 1100.0],
        days=_days(2),
        fills=fills,
        rejections=[],
        marks={"AAA": 11.06},
        starting_cash=1000.0,
    )
    gain = payload["final_equity"] - payload["starting_cash"]
    assert payload["metrics"]["total_return"] == pytest.approx(gain / 1000.0)
