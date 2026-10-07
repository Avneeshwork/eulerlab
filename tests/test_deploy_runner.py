"""Forward paper trading: catch-up, no double sends, and the halts."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.deploy import deployments as store
from eulerlab.deploy import runner
from eulerlab.features.panel import PanelRow


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


def _panel(n: int) -> list[PanelRow]:
    days = _weekdays(date(2024, 1, 1), n)
    out: list[PanelRow] = []
    for i, d in enumerate(days):
        for symbol, base, drift in (("AAA", 100.0, 1.0), ("BBB", 90.0, 2.0), ("CCC", 80.0, -0.5)):
            out.append(
                PanelRow(
                    day=d,
                    symbol=symbol,
                    close=base + drift * i,
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
    return store.create("top_two", mode="paper", capital=100_000, start=date(2024, 1, 15))


def test_a_run_trades_and_a_second_run_sends_nothing(deployment: store.Deployment) -> None:
    rows = _panel(30)
    first = runner.run(deployment, rows)
    assert first["status"] == "ok", first.get("reason")
    assert first["sent_this_run"] > 0
    assert {p["symbol"] for p in first["book"]} <= {"AAA", "BBB"}
    again = runner.run(store.load(deployment.id), rows)
    assert again["status"] == "ok"
    assert again["sent_this_run"] == 0
    assert again["equity"] == first["equity"]


def test_missed_days_are_caught_up_in_one_run(deployment: store.Deployment) -> None:
    runner.run(deployment, _panel(20))
    later = runner.run(store.load(deployment.id), _panel(32))
    assert later["status"] == "ok"
    assert later["traded_through"] > "2024-01-26"


def test_a_changed_past_halts_and_sends_nothing(deployment: store.Deployment) -> None:
    runner.run(deployment, _panel(25))
    # Revise history: CCC becomes the best stock on every past day.
    revised = [
        r
        if r.symbol != "CCC"
        else PanelRow(
            day=r.day, symbol="CCC", close=r.close + 500, volume=1000, turnover=1e7, isin="INECCC"
        )
        for r in _panel(26)
    ]
    state = runner.run(store.load(deployment.id), revised)
    assert state["status"] == "halted"
    assert "never placed" in state["reason"]
    assert store.load(deployment.id).status == "halted"
    # And it stays halted: the next run does not trade.
    assert runner.run(store.load(deployment.id), revised)["status"] == "halted"


def test_live_is_refused(deployment: store.Deployment) -> None:
    live = deployment.model_copy(update={"mode": "live"})
    with pytest.raises(RuntimeError, match="not enabled"):
        runner.make_oms(live)


def test_freshness_counts_weekdays_behind() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)  # 20:30 IST, Wednesday
    assert runner.freshness(date(2026, 10, 7), now) == ""
    assert "2 trading day(s) behind" in runner.freshness(date(2026, 10, 5), now)
