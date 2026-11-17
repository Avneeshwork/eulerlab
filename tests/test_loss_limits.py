"""Loss limits that act: reduce-only, then halt (ADR-092)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.deploy import deployments as store
from eulerlab.deploy import runner
from eulerlab.features.panel import PanelRow
from eulerlab.risk.limits import loss_limits


class TopTwo(Strategy):
    """Hold the two highest closes, equal weight, re-ranked every 3 sessions."""

    name = "top_two"
    lookback = 5
    rebalance_every = 3

    def target_weights(self, view: MarketView) -> dict[str, float]:
        ranked = sorted(view.history, key=lambda s: (-view.history[s][-1].close, s))
        return dict.fromkeys(ranked[:2], 0.5)


def _weekdays(start: date, n: int) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _falling_panel(n: int, *, fall_from: int = 15, per_day: float = 0.02) -> list[PanelRow]:
    """AAA and BBB lead and are held; from `fall_from` they lose `per_day` a session.

    BBB and CCC swap places every few days so the book keeps wanting to buy.
    """
    out: list[PanelRow] = []
    for i, d in enumerate(_weekdays(date(2024, 1, 1), n)):
        down = (1 - per_day) ** max(0, i - fall_from)
        wobble = 3.0 if (i // 4) % 2 else -3.0
        for symbol, close in (
            ("AAA", 200.0 * down),
            ("BBB", 150.0 * down + wobble),
            ("CCC", 150.0 * down - wobble),
        ):
            out.append(
                PanelRow(
                    day=d,
                    symbol=symbol,
                    close=close,
                    volume=1000,
                    turnover=1e7,
                    isin=f"INE{symbol}",
                )
            )
    return out


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> store.Deployment:
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "_strategy", lambda _id: TopTwo())
    monkeypatch.setattr(runner, "freshness", lambda *a, **k: "")
    monkeypatch.setattr(loss_limits, "CONFIG", tmp_path / "none.yaml")
    made = store.create("top_two", mode="paper", capital=100_000, start=date(2024, 1, 15))
    return _with(made, reduce_at=0.05, halt_at=0.60)


def _with(deployment: store.Deployment, **levels: float | None) -> store.Deployment:
    updated = deployment.model_copy(update=levels)
    store.save(updated)
    return updated


def _buys_after(state: dict[str, object], day: str) -> list[dict[str, object]]:
    fills = state.get("fills") or []
    assert isinstance(fills, list)
    return [f for f in fills if f["side"] == "buy" and str(f["day"]) > day]


def test_drawdown_ignores_a_withdrawal() -> None:
    state = {
        "curve": [["2024-01-01", 100.0], ["2024-01-02", 110.0], ["2024-01-03", 60.0]],
        # ₹50 taken out on the 3rd: trading made 110 -> 110, nothing was lost.
        "flows": [{"applied_day": "2024-01-03", "amount": -50.0}],
    }
    now, worst = loss_limits.drawdown(state, 100.0)
    assert now == pytest.approx(0.0, abs=1e-9) and worst == pytest.approx(0.0, abs=1e-9)
    state["flows"] = []
    now, _ = loss_limits.drawdown(state, 100.0)
    assert now == pytest.approx(50 / 110)


def test_a_drawdown_past_the_reduce_level_refuses_buys_from_the_next_session(
    deployment: store.Deployment,
) -> None:
    first = runner.run(deployment, _falling_panel(22))
    assert first["status"] == "ok", first.get("reason")
    assert first["loss_limit"]["drawdown"] >= 0.05
    assert first["loss_limit"]["action"] == "reducing"
    reduced = store.load(deployment.id)
    assert loss_limits.is_reducing(reduced)
    since = reduced.reducing[0]["from"]
    assert since > first["traded_through"]

    later = runner.run(reduced, _falling_panel(40))
    assert later["status"] == "ok", later.get("reason")
    assert _buys_after(later, first["traded_through"]) == []
    assert later["refused_reducing"] > 0
    # Sells still go through.
    assert any(f["side"] == "sell" and f["day"] >= since for f in later["fills"])
    # A replay of the same days sends nothing new and does not see a changed history.
    again = runner.run(store.load(deployment.id), _falling_panel(40))
    assert again["status"] == "ok" and again["sent_this_run"] == 0


def test_resuming_lets_the_book_buy_again_without_rewriting_the_past(
    deployment: store.Deployment,
) -> None:
    runner.run(deployment, _falling_panel(22))
    middle = runner.run(store.load(deployment.id), _falling_panel(30))
    resumed = loss_limits.stop_reducing(
        store.load(deployment.id), date.fromisoformat(middle["traded_through"]), "operator"
    )
    # Above the reduce level now, so the next run must not reopen the window.
    resumed = _with(resumed, reduce_at=None)
    assert not loss_limits.is_reducing(resumed)
    after = runner.run(resumed, _falling_panel(40))
    assert after["status"] == "ok", after.get("reason")
    assert _buys_after(after, middle["traded_through"])


def test_a_drawdown_past_the_halt_level_trips_the_kill_switch(
    deployment: store.Deployment,
) -> None:
    deployment = _with(deployment, reduce_at=None, halt_at=0.05)
    state = runner.run(deployment, _falling_panel(22))
    assert state["status"] == "halted"
    assert "loss limit" in state["reason"]
    assert store.load(deployment.id).status == "halted"
    assert (deployment.folder / "KILL_SWITCH").exists()


def test_no_levels_means_no_action(deployment: store.Deployment) -> None:
    deployment = _with(deployment, reduce_at=None, halt_at=None)
    state = runner.run(deployment, _falling_panel(30))
    assert state["status"] == "ok"
    assert state["loss_limit"]["action"] == ""
    assert not store.load(deployment.id).reducing


def test_the_shipped_config_loads() -> None:
    limits = loss_limits.load()
    assert limits.reduce_at is not None and limits.halt_at is not None
    assert limits.reduce_at < limits.halt_at


def test_the_routes_turn_reduce_only_on_and_off_and_set_levels(
    deployment: store.Deployment,
) -> None:
    from eulerlab.api import deploy_routes as r

    runner.run(_with(deployment, reduce_at=None), _falling_panel(20))
    on = r.reduce_only(deployment.id, r.ReduceRequest(on=True))
    assert on["ok"] and on["deployment"]["reducing_now"] is True
    assert on["deployment"]["reducing"][0]["by"] == "operator"
    off = r.reduce_only(deployment.id, r.ReduceRequest(on=False))
    # Nothing was traded inside the window, so it is dropped rather than kept.
    assert off["ok"] and off["deployment"]["reducing_now"] is False
    assert off["deployment"]["reducing"] == []

    bad = r.set_limits(deployment.id, r.LimitsRequest(reduce_at=0.3, halt_at=0.2))
    assert bad["ok"] is False
    good = r.set_limits(deployment.id, r.LimitsRequest(reduce_at=0.08, halt_at=0.15))
    assert good["ok"] and good["deployment"]["limits"] == {"reduce_at": 0.08, "halt_at": 0.15}
    assert r.reduce_only("nobody", r.ReduceRequest(on=True))["ok"] is False


def test_going_reduce_only_is_announced(deployment: store.Deployment) -> None:
    from eulerlab.deploy import signals

    state = {
        "status": "ok",
        "loss_limit": {"action": "reducing", "drawdown": 0.112},
        "fills": [],
    }
    text = signals.message(deployment, {}, state)
    assert text is not None and "REDUCE-ONLY" in text and "11.2%" in text
    assert signals.message(deployment, {}, {"status": "ok", "fills": []}) is None


def test_a_book_not_run_since_limits_existed_still_shows_its_drawdown(
    deployment: store.Deployment,
) -> None:
    from eulerlab.api import deploy_routes as r

    runner.run(_with(deployment, reduce_at=None), _falling_panel(30))
    state = store.read_state(deployment) or {}
    expected = state["loss_limit"]["drawdown"]
    # As a book's state looked before this change: no measurement in it.
    store.write_state(deployment, {k: v for k, v in state.items() if k != "loss_limit"})

    shown = r._summary(store.load(deployment.id))["state"]["loss_limit"]

    assert shown["drawdown"] == pytest.approx(expected, abs=1e-4)
    assert shown["action"] is None
