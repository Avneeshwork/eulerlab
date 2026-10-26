"""FX pays the recorded bid-ask spread in every engine (HISTORY #30)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eulerlab.backtest import vector
from eulerlab.backtest.event_driven import TierBResult, reconcile
from eulerlab.backtest.event_driven import run as run_tier_b
from eulerlab.backtest.strategies import BuyAndHold
from eulerlab.features.panel import PanelRow

START = date(2024, 1, 1)
SPREAD = 0.0004


def _fx_panel(n_pairs: int = 6, n_days: int = 200) -> list[PanelRow]:
    rows: list[PanelRow] = []
    for p in range(n_pairs):
        price = 1.0 + p / 10
        for d in range(n_days):
            price *= 1.0 + (0.0003 if (d + p) % 3 else -0.0004)
            rows.append(
                PanelRow(
                    day=START + timedelta(days=d),
                    symbol=f"PAIR{p}",
                    close=price,
                    volume=1.0,
                    turnover=1e9 - p,
                    isin=f"FX{p:04d}",
                    spread=SPREAD * (1 + p),
                )
            )
    return rows


def _run(engine: str, rows: list[PanelRow]) -> vector.BacktestResult | TierBResult:
    run = vector.run if engine == "A" else run_tier_b
    return run(
        rows,
        BuyAndHold(top_n=3),
        warmup=30,
        rebalance_every=10,
        asset_class="fx",
        cost_mode="realistic",
    )


@pytest.mark.parametrize("engine", ["A", "B"])
def test_each_fx_fill_pays_half_the_spread_recorded_that_day(engine: str) -> None:
    rows = _fx_panel()
    spread = {(r.symbol, r.day): r.spread for r in rows}
    result = _run(engine, rows)
    fills = result.fills
    assert fills, "the strategy must trade for this test to mean anything"
    for fill in fills:
        expected = spread[(fill.symbol, fill.day)] / 2 * fill.quantity
        assert fill.cost == pytest.approx(expected)
    assert sum(f.cost for f in fills) > 0


def test_the_engines_still_agree_on_fx() -> None:
    rows = _fx_panel()
    a, b = _run("A", rows), _run("B", rows)
    found = reconcile(a.equity, b.equity)
    assert found.agrees, found


def test_replication_mode_still_charges_nothing() -> None:
    rows = _fx_panel()
    free = vector.run(
        rows, BuyAndHold(top_n=3), warmup=30, rebalance_every=10, asset_class="fx",
        cost_mode="replication",
    )  # fmt: skip
    assert sum(f.cost for f in free.fills) == 0
