"""A deployment's report: the backtest report's payload on its own record."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from eulerlab.deploy import analysis
from eulerlab.deploy import deployments as store


def _deployment() -> store.Deployment:
    return store.Deployment(
        id="paper-x-2026-10-01-abcdef",
        strategy_id="x",
        mode="paper",
        capital=1000.0,
        start=date(2026, 10, 1),
        created_at="2026-10-01T00:00:00+00:00",
    )


def _state() -> dict[str, Any]:
    """₹1,000: buys 10 at 100 (₹1 cost), up 10%, then ₹1,000 added, then 5% more."""
    return {
        "equity": 2152.95,
        "cash": 1152.95,
        "curve": [["2026-10-02", 999.0], ["2026-10-05", 1099.0], ["2026-10-06", 2152.95]],
        "flows": [{"amount": 1000.0, "applied_day": "2026-10-06"}],
        "fills": [
            {
                "day": "2026-10-02",
                "symbol": "A",
                "side": "buy",
                "quantity": 10,
                "price": 100.0,
                "cost": 1.0,
            }
        ],
        "book": [{"symbol": "A", "quantity": 10, "last_price": 115.5, "value": 1155.0}],
    }


def test_the_report_is_time_weighted_and_its_rupees_are_real() -> None:
    out = analysis.build(_deployment(), _state(), None, None)
    assert out["ok"]
    report = out["report"]
    money = report["deployment"]
    assert money["put_in"] == 2000.0 and money["made"] == pytest.approx(152.95)
    # 999/1000 * 1099/999 * 2152.95/2099: day one's cost counts, the deposit does not.
    expected = 2152.95 / 2099 * 1.099 - 1
    assert report["metrics"]["total_return"] == pytest.approx(expected, abs=1e-6)
    assert money["time_weighted_return"] == pytest.approx(expected, abs=1e-6)
    assert report["equity"]["days"][0] == "2026-10-01", "starts at the capital"
    assert len(money["actual_equity"]) == len(report["equity"]["values"])
    assert any("added or withdrawn" in w for w in report["warnings"])


def test_the_fills_reconcile_against_rupees_made() -> None:
    report = analysis.build(_deployment(), _state(), None, None)["report"]
    rec = report["reconciliation"]
    # Bought ₹1,000 + ₹1 cost, now worth ₹1,155: ₹154 attributed, ₹152.95 made.
    assert rec["attributed"] == 154.0 and rec["equity_change"] == pytest.approx(152.95)


def test_the_backtest_is_carried_beside_it() -> None:
    tested = {
        "period": ["2020-01-01", "2024-12-31"],
        "metrics": {"sharpe": 1.2, "drawdown": {"depth": -0.2}},
    }
    report = analysis.build(_deployment(), _state(), None, tested)["report"]
    assert report["backtest"]["metrics"]["sharpe"] == 1.2
    assert report["backtest"]["max_drawdown"] == -0.2


def test_truncated_fills_are_said_and_the_full_file_wins() -> None:
    state = {**_state(), "fills_total": 450}
    report = analysis.build(_deployment(), state, None, None)["report"]
    assert any("Only the last 1 of 450" in w for w in report["warnings"])
    full = analysis.build(_deployment(), state, state["fills"], None)["report"]
    assert not any("Only the last" in w for w in full["warnings"])


def test_nothing_to_analyse_says_why() -> None:
    out = analysis.build(_deployment(), {"reason": "waiting for the panel"}, None, None)
    assert not out["ok"] and "waiting for the panel" in out["error"]


def test_one_rule_decides_what_can_paper_trade() -> None:
    """2026-10-17: the preflight passed buy_and_hold, which the deploy route refused."""
    from eulerlab.api import server
    from eulerlab.api.deploy_routes import DeployRequest, deploy
    from eulerlab.deploy.runner import paper_blocker

    assert paper_blocker("momentum_12_1") == ""
    assert paper_blocker("nifty_calm_rise_overnight") == ""
    assert "control" in paper_blocker("buy_and_hold")
    assert "not wired to paper trading" in paper_blocker("tweezer_bottom")
    for sid in ("buy_and_hold", "tweezer_bottom"):
        checked = server.deploy_preflight(server.PreflightRequest(strategy=sid, mode="paper"))
        assert not checked["ok"]
        refused = deploy(DeployRequest(strategy=sid, mode="paper", capital=1_000_000.0))
        assert not refused["ok"] and "cannot paper-trade" in refused["error"]
