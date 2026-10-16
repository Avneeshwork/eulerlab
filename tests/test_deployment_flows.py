"""Dated paper cash flows preserve replayed orders and exclude deposits from return."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from pathlib import Path

import pytest

from eulerlab.api import deploy_routes
from eulerlab.backtest.event_driven import run as run_events
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.deploy import deployments as store
from eulerlab.deploy import runner
from eulerlab.deploy.deployments import Deployment
from test_deploy_runner import TopTwo, _panel


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Deployment:
    monkeypatch.setattr(store, "ROOT", tmp_path / "deployments")
    monkeypatch.setattr(runner, "_strategy", lambda _id: TopTwo())
    monkeypatch.setattr(runner, "freshness", lambda *a, **k: "")
    return store.create("top_two", mode="paper", capital=100_000, start=date(2024, 1, 15))


def test_deposit_applies_after_recorded_decision_and_return_excludes_it(
    deployment: Deployment,
) -> None:
    rows = _panel(30)
    first = runner.run(deployment, rows)
    assert first["status"] == "ok"
    last_decided = first["last_decided"]
    flow = {
        "amount": 50_000.0,
        "last_decided": last_decided,
        "entered_at": "2026-10-15T10:00:00.000001+00:00",
    }
    updated = deployment.model_copy(update={"flows": [flow]})

    extended = _panel(33)
    after = runner.run(updated, extended)

    assert after["status"] == "ok", after.get("reason")
    assert after["invested"] == 150_000
    assert after["flows"][0]["amount"] == 50_000
    assert after["pending"] == []
    assert after["sent_this_run"] > 0
    old_fill_days = {fill["day"] for fill in first["fills"]}
    assert all(
        fill["day"] in old_fill_days for fill in after["fills"] if fill["day"] <= last_decided
    )
    assert after["sent_this_run"] == sum(
        fill["day"] > first["traded_through"] for fill in after["fills"]
    )


def test_time_weighted_return_does_not_count_a_cash_only_deposit() -> None:
    class CashOnly(Strategy):
        name = "cash_only"
        lookback = 1

        def target_weights(self, view: MarketView) -> dict[str, float]:
            return {}

    days = _panel(6)
    last_decided = min(row.day for row in days).isoformat()
    result = run_events(
        days,
        CashOnly(),
        starting_cash=100_000,
        warmup=0,
        rebalance_every=5,
        asset_class="equity",
        cash_flows=[
            {
                "amount": 50_000,
                "last_decided": last_decided,
                "entered_at": "flow-1",
            }
        ],
    )

    assert result.final_equity == 150_000
    assert result.total_return == pytest.approx(0.0)


def test_withdrawal_rebalances_down_and_does_not_make_cash_negative(
    deployment: Deployment,
) -> None:
    rows = _panel(30)
    first = runner.run(deployment, rows)
    flow = {
        "amount": -20_000.0,
        "last_decided": first["last_decided"],
        "entered_at": "2026-10-15T10:00:00.000002+00:00",
    }
    updated = deployment.model_copy(update={"flows": [flow]})

    state = runner.run(updated, _panel(33))

    assert state["status"] == "ok", state.get("reason")
    assert state["invested"] == 80_000
    assert state["cash"] >= 0
    assert state["flows"][0]["amount"] == -20_000


def test_cash_flow_route_guards_and_records_pending_flow(
    deployment: Deployment, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from eulerlab.ingest import filelock

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(filelock, "exclusive", lambda *_args, **_kwargs: nullcontext())
    deploy_routes.RUNNING.clear()
    store.write_state(
        deployment,
        {
            "status": "ok",
            "as_of": "2024-02-02",
            "last_decided": "2024-02-01",
            "equity": 10_000.0,
            "traded_through": "2024-02-02",
        },
    )

    too_large = deploy_routes.cash_flow(
        deployment.id, deploy_routes.FlowRequest(action="withdraw", amount=9_001)
    )
    assert not too_large["ok"] and "₹1,000" in too_large["error"]

    added = deploy_routes.cash_flow(
        deployment.id, deploy_routes.FlowRequest(action="add", amount=5_000)
    )
    assert added["ok"]
    assert added["flow"]["last_decided"] == "2024-02-01"
    assert added["deployment"]["state"]["pending"][0]["amount"] == 5_000

    live = deployment.model_copy(update={"mode": "live"})
    store.save(live)
    refused = deploy_routes.cash_flow(
        live.id, deploy_routes.FlowRequest(action="add", amount=5_000)
    )
    assert not refused["ok"] and "live" in refused["error"]

    stopped = store.set_status(deployment, "stopped")
    refused = deploy_routes.cash_flow(
        stopped.id, deploy_routes.FlowRequest(action="add", amount=5_000)
    )
    assert not refused["ok"] and "stopped" in refused["error"]


def test_flowless_backtest_return_remains_final_over_starting_cash() -> None:
    from eulerlab.backtest.event_driven import TierBResult

    result = TierBResult(
        strategy="fixture",
        days=[date(2024, 1, 2)],
        equity=[110_000],
        starting_cash=100_000,
    )
    assert result.total_return == pytest.approx(0.1)
