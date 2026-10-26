"""Tier A engine: no lookahead, one cost path, and a control that must work.

The engine is tested against situations whose answer is known before it runs.
An engine that produces a plausible equity curve tells you nothing; one that
reproduces buy-and-hold, and refuses to profit from a signal it should not
have seen, tells you a great deal.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from eulerlab.backtest.strategies import BuyAndHold, RankAndHold
from eulerlab.backtest.strategy import MarketView, Strategy, normalise
from eulerlab.backtest.vector import APPROXIMATIONS, run
from eulerlab.features.panel import PanelRow

START = date(2024, 1, 1)


def _panel(n_symbols: int = 60, n_days: int = 300, drift: float = 0.0005) -> list[PanelRow]:
    """A deterministic panel where every symbol drifts at a known rate."""
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
                    turnover=1_000_000.0 - s,
                    isin=f"TEST{s:06d}",
                )
            )
    return rows


class _Constant(Strategy):
    """Holds a fixed basket; the simplest possible strategy."""

    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols
        self.name = "constant"

    def target_weights(self, view: MarketView) -> dict[str, float]:
        return dict.fromkeys(self.symbols, 1.0 / len(self.symbols))


# --- the control ---


def test_buy_and_hold_tracks_a_uniformly_drifting_market() -> None:
    """If the engine cannot reproduce buy-and-hold on a market where every
    stock rises at the same known rate, nothing else it says is worth reading.
    """
    rows = _panel(n_symbols=40, n_days=320, drift=0.001)
    result = run(
        rows, BuyAndHold(top_n=20), warmup=60, rebalance_every=10_000, asset_class="equity"
    )
    assert result.final_equity > result.starting_cash
    # 259 remaining days at 0.1% a day, less entry costs. Generous bounds:
    # the test is that it is in the right order of magnitude, not exact.
    assert 1.15 < result.final_equity / result.starting_cash < 1.40


def test_a_falling_market_loses_money() -> None:
    rows = _panel(n_symbols=40, n_days=320, drift=-0.001)
    result = run(
        rows, BuyAndHold(top_n=20), warmup=60, rebalance_every=10_000, asset_class="equity"
    )
    assert result.final_equity < result.starting_cash


# --- the firewall ---


def test_a_strategy_cannot_see_beyond_its_decision_date() -> None:
    """The structural guarantee: the view contains no row after as_of, so a
    strategy cannot look forward even if it tries."""
    rows = _panel(n_symbols=10, n_days=300)
    seen: list[tuple[date, date]] = []

    class Spy(Strategy):
        name = "spy"

        def target_weights(self, view: MarketView) -> dict[str, float]:
            for symbol in view.symbols():
                last = view.history[symbol][-1].day
                seen.append((view.as_of, last))
            return {}

    run(rows, Spy(), warmup=60, rebalance_every=50, asset_class="equity")
    assert seen
    for as_of, last_row in seen:
        assert last_row <= as_of


def test_the_fill_happens_after_the_decision_day() -> None:
    """Filling on the decision bar's own close is the classic vectorised
    lookahead. Every fill must be dated later than the view that caused it."""
    rows = _panel(n_symbols=10, n_days=300)
    decision_days: list[date] = []

    class Recorder(Strategy):
        name = "recorder"

        def target_weights(self, view: MarketView) -> dict[str, float]:
            decision_days.append(view.as_of)
            return {"SYM000": 1.0}

    result = run(rows, Recorder(), warmup=60, rebalance_every=50, asset_class="equity")
    assert result.fills
    for fill in result.fills:
        assert any(fill.day > d for d in decision_days)


# --- costs: exactly one path ---


def test_replication_mode_charges_nothing() -> None:
    rows = _panel(n_symbols=20, n_days=320)
    result = run(
        rows, BuyAndHold(top_n=10), warmup=60, cost_mode="replication", asset_class="equity"
    )
    assert result.total_cost == 0.0


def test_realistic_mode_charges_something_on_every_fill() -> None:
    rows = _panel(n_symbols=20, n_days=320)
    result = run(rows, BuyAndHold(top_n=10), warmup=60, cost_mode="realistic", asset_class="equity")
    assert result.fills
    assert result.total_cost > 0
    assert all(f.cost > 0 for f in result.fills)


def test_costs_reduce_the_final_equity() -> None:
    """The two modes must differ by exactly the costs, which is what makes
    'does this survive costs?' a single flag."""
    rows = _panel(n_symbols=20, n_days=320)
    free = run(rows, BuyAndHold(top_n=10), warmup=60, cost_mode="replication", asset_class="equity")
    paid = run(rows, BuyAndHold(top_n=10), warmup=60, cost_mode="realistic", asset_class="equity")
    assert paid.final_equity < free.final_equity


def test_more_frequent_rebalancing_costs_more() -> None:
    """The asymmetry that kills high-turnover strategies. If this did not
    hold, the cost model would not be reaching the engine.

    The leaders rotate every 30 days, so a frequent rebalance has something to
    trade. On `_panel` the ranking never moves and both runs make the same ~30
    trades, which is how this test went red on a ₹0.13 difference when buys
    became limited to the cash on hand (HISTORY #28)."""
    rows = [
        replace(
            row, turnover=1_000_000.0 - (int(row.symbol[3:]) + (row.day - START).days // 30) % 40
        )
        for row in _panel(n_symbols=40, n_days=320)
    ]
    rare = run(
        rows,
        RankAndHold("turnover_liquidity", top_n=10, min_names=20),
        warmup=70,
        rebalance_every=100,
        asset_class="equity",
    )
    often = run(
        rows,
        RankAndHold("turnover_liquidity", top_n=10, min_names=20),
        warmup=70,
        rebalance_every=5,
        asset_class="equity",
    )
    assert often.total_cost > rare.total_cost


# --- weights ---


def test_gross_exposure_is_capped_by_the_engine_not_the_strategy() -> None:
    """Leverage is the engine's decision. A strategy asking for 5x is scaled,
    not rejected, so engine behaviour never depends on strategy arithmetic."""
    weights = normalise({"A": 3.0, "B": 2.0}, gross_cap=1.0)
    assert sum(abs(w) for w in weights.values()) == pytest.approx(1.0)


def test_weights_within_the_cap_are_left_alone() -> None:
    weights = normalise({"A": 0.3, "B": 0.2}, gross_cap=1.0)
    assert weights == {"A": 0.3, "B": 0.2}


def test_a_non_finite_weight_cannot_become_a_position() -> None:
    """A NaN from a division inside a strategy must not silently be held."""
    assert normalise({"A": float("nan"), "B": 1.0}) == {"B": 1.0}


def test_a_zero_weight_is_the_same_as_being_absent() -> None:
    assert normalise({"A": 0.0, "B": 1.0}) == {"B": 1.0}


def test_an_empty_target_holds_nothing() -> None:
    assert normalise({}) == {}


# --- honesty about limits ---


def test_the_engine_publishes_its_approximations() -> None:
    """A Tier A number read as a Tier B number is worse than no number."""
    assert APPROXIMATIONS
    joined = " ".join(APPROXIMATIONS).lower()
    assert "intrabar" in joined
    assert "next bar" in joined


def test_a_panel_shorter_than_the_warmup_returns_nothing_rather_than_guessing() -> None:
    rows = _panel(n_symbols=5, n_days=30)
    result = run(rows, BuyAndHold(top_n=3), warmup=253, asset_class="equity")
    assert result.equity == []
    assert result.final_equity == result.starting_cash


def test_a_thin_cross_section_holds_nothing_rather_than_whatever_qualified() -> None:
    """Otherwise the early portfolio is an accident of data coverage."""
    rows = _panel(n_symbols=5, n_days=300)
    strategy = RankAndHold("turnover_liquidity", top_n=3, min_names=50)
    result = run(rows, strategy, warmup=70, rebalance_every=50, asset_class="equity")
    assert result.fills == []


# --- the valuation bug, which produced a -50% drawdown out of nothing ---


def test_a_holding_is_marked_at_its_last_known_price_when_it_does_not_trade() -> None:
    """The bug this test exists for.

    Measured on the real panel, 31 of 400 symbols have at least one missing
    day inside their own listed span. Valuing a holding at nothing on those
    days dropped its whole value out of the portfolio and restored it the next
    day, manufacturing a **-50% maximum drawdown** that was pure artefact and
    flipping the strategy's return from +7.8% to -13.1%.
    """
    rows: list[PanelRow] = []
    for d in range(300):
        day = START + timedelta(days=d)
        # ANCHOR trades every day; GAPPY skips a stretch in the middle.
        rows.append(
            PanelRow(
                day=day, symbol="ANCHOR", close=100.0, volume=1.0, turnover=9e9, isin="TESTKEY"
            )
        )
        if not (250 <= d < 260):
            rows.append(
                PanelRow(
                    day=day, symbol="GAPPY", close=100.0, volume=1.0, turnover=8e9, isin="TESTKEY"
                )
            )

    result = run(
        rows,
        _Constant(["ANCHOR", "GAPPY"]),
        warmup=200,
        rebalance_every=10_000,
        asset_class="equity",
    )
    assert result.equity
    # Prices are flat, so equity must be flat too. Any dip is the artefact.
    worst = min(result.equity)
    assert worst > result.equity[0] * 0.95


def test_an_instrument_that_did_not_trade_cannot_be_traded() -> None:
    """Valuation carries forward; execution does not. A fill at a made-up
    price is worse than no fill."""
    rows: list[PanelRow] = []
    for d in range(300):
        day = START + timedelta(days=d)
        rows.append(
            PanelRow(
                day=day, symbol="ANCHOR", close=100.0, volume=1.0, turnover=9e9, isin="TESTKEY"
            )
        )
        if d < 250:
            rows.append(
                PanelRow(
                    day=day, symbol="HALTED", close=100.0, volume=1.0, turnover=8e9, isin="TESTKEY"
                )
            )

    result = run(
        rows, _Constant(["ANCHOR", "HALTED"]), warmup=260, rebalance_every=10, asset_class="equity"
    )
    assert all(f.symbol != "HALTED" for f in result.fills)


# --- the liquidity screen ---


def test_a_turnover_floor_excludes_untradeable_names() -> None:
    """Unfiltered, top-30 momentum bought names on Rs 49,839 of daily
    turnover, where a Rs 33,000 position is most of a day's volume and the
    fill price in this engine is fiction."""
    rows: list[PanelRow] = []
    for d in range(300):
        day = START + timedelta(days=d)
        rows.append(
            PanelRow(
                day=day,
                symbol="LIQUID",
                close=100.0 * (1.002**d),
                volume=1.0,
                turnover=9e9,
                isin="TESTL",
            )
        )
        rows.append(
            PanelRow(
                day=day,
                symbol="THIN",
                close=100.0 * (1.01**d),
                volume=1.0,
                turnover=50_000.0,
                isin="TESTT",
            )
        )

    strategy = RankAndHold("momentum_12_1", top_n=5, min_names=1, min_turnover=1e6)
    view = MarketView(
        as_of=rows[-1].day,
        history={
            "LIQUID": [r for r in rows if r.symbol == "LIQUID"],
            "THIN": [r for r in rows if r.symbol == "THIN"],
        },
    )
    weights = strategy.target_weights(view)
    assert "THIN" not in weights
    assert "LIQUID" in weights


def test_the_default_is_no_filter_so_the_naive_behaviour_is_visible() -> None:
    """Defaulting the screen on would quietly prevent a result worth seeing."""
    strategy = RankAndHold("momentum_12_1", top_n=5)
    assert strategy.min_turnover == 0.0
