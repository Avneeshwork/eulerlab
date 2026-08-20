"""Tier B: the same Strategy, an explicit order lifecycle, and reconciliation.

The headline test is that the two engines agree. Everything else exists to
make sure Tier B is genuinely doing more work rather than being a slow copy of
Tier A — an engine that agrees because it is the same code proves nothing.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eulerlab.backtest import event_driven, vector
from eulerlab.backtest.events import Fill, Order, Portfolio, client_order_id
from eulerlab.backtest.strategies import BuyAndHold, RankAndHold
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.costs.schedule import Side
from eulerlab.features.panel import PanelRow

START = date(2024, 1, 1)


def _panel(n_symbols: int = 30, n_days: int = 320, drift: float = 0.0008) -> list[PanelRow]:
    rows: list[PanelRow] = []
    for s in range(n_symbols):
        price = 100.0
        for d in range(n_days):
            price *= 1.0 + drift
            rows.append(
                PanelRow(
                    day=START + timedelta(days=d),
                    symbol=f"SYM{s:03d}",
                    close=price,
                    volume=1000.0,
                    turnover=1e9 - s,
                    isin=f"TEST{s:06d}",
                )
            )
    return rows


# --- the headline: one interface, two engines, same answer ---


def test_the_same_strategy_object_runs_in_both_engines_unadapted() -> None:
    """CLAUDE.md's rule, as an executable check. No wrapper, no adapter, no
    isinstance - if Tier B needed one, the interface would have failed."""
    rows = _panel()
    strategy = BuyAndHold(top_n=10)
    a = vector.run(rows, strategy, warmup=60, rebalance_every=50)
    b = event_driven.run(rows, strategy, warmup=60, rebalance_every=50)
    assert a.equity and b.equity


def test_the_two_engines_agree_to_floating_point_noise() -> None:
    """Configured identically they must produce the same curve. Measured on
    the real panel the difference is 7e-16 relative - machine epsilon."""
    rows = _panel()
    for strategy in (
        BuyAndHold(top_n=10),
        RankAndHold("turnover_liquidity", top_n=10, min_names=5),
    ):
        a = vector.run(rows, strategy, warmup=70, rebalance_every=50)
        b = event_driven.run(rows, strategy, warmup=70, rebalance_every=50)
        r = event_driven.reconcile(a.equity, b.equity)
        assert r.agrees, f"{strategy.describe()} diverged by {r.max_relative:.2e}"


def test_tier_a_is_never_the_optimistic_one() -> None:
    """A cheap screen may reject something good; it must never pass something
    bad. If Tier B comes out lower, Tier A is flattering."""
    rows = _panel()
    strategy = BuyAndHold(top_n=10)
    a = vector.run(rows, strategy, warmup=70, rebalance_every=50)
    b = event_driven.run(rows, strategy, warmup=70, rebalance_every=50)
    assert event_driven.reconcile(a.equity, b.equity).tier_a_is_pessimistic


def test_agreement_is_not_flagged_as_a_pessimism_violation() -> None:
    """An exact == here cried wolf on identical curves, which teaches the
    reader to skip the check."""
    curve = [100.0, 101.0, 102.0]
    noisy = [100.0, 101.0, 102.0 + 1e-10]
    assert event_driven.reconcile(curve, noisy).tier_a_is_pessimistic


def test_a_genuine_divergence_is_reported() -> None:
    r = event_driven.reconcile([100.0, 200.0], [100.0, 150.0])
    assert not r.agrees
    assert not r.tier_a_is_pessimistic


# --- Tier B does more, which is the point ---


def test_tier_b_records_rejections_that_tier_a_can_only_skip() -> None:
    """An instrument that did not print cannot be traded. Tier A silently
    skips it; Tier B records why, which is what live would have done."""
    rows: list[PanelRow] = []
    for d in range(320):
        day = START + timedelta(days=d)
        rows.append(
            PanelRow(
                day=day, symbol="ALWAYS", close=100.0, volume=1.0, turnover=9e9, isin="TESTKEY"
            )
        )
        if d % 7 != 3:
            rows.append(
                PanelRow(
                    day=day, symbol="PATCHY", close=100.0, volume=1.0, turnover=8e9, isin="TESTKEY"
                )
            )

    class Both(Strategy):
        name = "both"

        def target_weights(self, view: MarketView) -> dict[str, float]:
            return {"ALWAYS": 0.5, "PATCHY": 0.5}

    # Rebalance daily. With a weekly rebalance the fill day happened to land
    # on the same weekday every time and never coincided with a missing one -
    # the test passed vacuously rather than exercising the path.
    result = event_driven.run(rows, Both(), warmup=60, rebalance_every=1)
    assert result.orders
    assert result.rejections, "no order ever landed on a non-trading day"
    assert all(r.reason for r in result.rejections)
    assert all(r.symbol == "PATCHY" for r in result.rejections)


def test_every_order_carries_a_deterministic_unique_id() -> None:
    """Deterministic ids are what stop a retry double-sending. That property
    is worthless if only live code has it."""
    rows = _panel()
    result = event_driven.run(rows, BuyAndHold(top_n=10), warmup=60, rebalance_every=40)
    ids = [o.client_order_id for o in result.orders]
    assert ids
    assert len(set(ids)) == len(ids)


def test_the_same_intention_always_produces_the_same_id() -> None:
    a = client_order_id("strat", date(2024, 5, 1), "ACME", 3)
    b = client_order_id("strat", date(2024, 5, 1), "ACME", 3)
    assert a == b


def test_a_different_sequence_produces_a_different_id() -> None:
    a = client_order_id("strat", date(2024, 5, 1), "ACME", 3)
    b = client_order_id("strat", date(2024, 5, 1), "ACME", 4)
    assert a != b


def test_the_order_schema_carries_algo_id_from_day_one() -> None:
    """CLAUDE.md compliance stub S-001: nullable, unused, present."""
    order = Order(
        client_order_id="x",
        strategy_id="s",
        signal_day=date(2024, 1, 1),
        symbol="ACME",
        side=Side.BUY,
        quantity=1,
    )
    assert order.algo_id is None


# --- portfolio accounting, which Sprint 12 will assert against ---


def _fill(side: Side, qty: int, price: float, cost: float = 0.0) -> Fill:
    return Fill(
        client_order_id="x",
        day=START,
        symbol="ACME",
        side=side,
        quantity=qty,
        price=price,
        cost=cost,
    )


def test_a_buy_reduces_cash_by_notional_plus_cost() -> None:
    p = Portfolio(cash=10_000.0)
    p.apply(_fill(Side.BUY, 10, 100.0, cost=5.0))
    assert p.cash == pytest.approx(10_000 - 1_000 - 5)
    assert p.holdings() == {"ACME": 10}


def test_a_round_trip_at_the_same_price_loses_exactly_the_costs() -> None:
    """The invariant Sprint 12 is built on: zero alpha must equal exact cost
    drag, never approximately."""
    p = Portfolio(cash=10_000.0)
    p.apply(_fill(Side.BUY, 10, 100.0, cost=5.0))
    p.apply(_fill(Side.SELL, 10, 100.0, cost=5.0))
    assert p.cash == pytest.approx(10_000 - 10)
    assert p.total_costs == pytest.approx(10.0)
    assert p.holdings() == {}


def test_a_profitable_round_trip_realises_the_gain_net_of_costs() -> None:
    p = Portfolio(cash=10_000.0)
    p.apply(_fill(Side.BUY, 10, 100.0, cost=5.0))
    p.apply(_fill(Side.SELL, 10, 110.0, cost=5.0))
    # Bought for 1005 all-in, sold for 1100 less 5 of cost.
    assert p.realised_pnl == pytest.approx(1100 - 1005 - 5)


def test_a_partial_exit_realises_only_its_share_of_the_basis() -> None:
    """Realising the whole basis on a partial sale would overstate the loss
    and leave the remaining position valued at nothing."""
    p = Portfolio(cash=10_000.0)
    p.apply(_fill(Side.BUY, 10, 100.0))
    p.apply(_fill(Side.SELL, 4, 100.0))
    assert p.holdings() == {"ACME": 6}
    assert p.positions["ACME"].cost_basis == pytest.approx(600.0)


def test_equity_is_cash_plus_marked_positions() -> None:
    p = Portfolio(cash=10_000.0)
    p.apply(_fill(Side.BUY, 10, 100.0))
    assert p.equity({"ACME": 120.0}) == pytest.approx(9_000 + 1_200)


def test_replication_mode_charges_nothing_in_tier_b_either() -> None:
    rows = _panel()
    result = event_driven.run(rows, BuyAndHold(top_n=10), warmup=60, cost_mode="replication")
    assert result.total_cost == 0.0


def test_realistic_mode_charges_through_the_shared_cost_path() -> None:
    """Tier B has no cost model of its own - that is the double-costing bug
    the reference system had to disable with a comment."""
    rows = _panel()
    result = event_driven.run(rows, BuyAndHold(top_n=10), warmup=60, cost_mode="realistic")
    assert result.total_cost > 0
