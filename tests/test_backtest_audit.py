"""Backtester fixes from the 2026-11-01 line-by-line review (HISTORY #53)."""

from __future__ import annotations

from datetime import date

from eulerlab.backtest.event_driven import TierBResult
from eulerlab.backtest.strategy import MarketView, Strategy, long_only
from eulerlab.features.panel import PanelRow


def test_adjusting_for_a_split_scales_volume_up_and_keeps_turnover() -> None:
    row = PanelRow(
        day=date(2019, 12, 18),
        symbol="NIFTYBEES",
        close=1292.5,
        volume=1_000.0,
        turnover=1_292_500.0,
        open=1290.0,
        high=1300.0,
        low=1280.0,
    )
    adjusted = row.adjusted(10.0)
    assert adjusted.close == 129.25
    assert adjusted.volume == 10_000.0
    assert adjusted.turnover == row.turnover
    # Rupees traded are unchanged by a change of units.
    assert adjusted.close * adjusted.volume == row.close * row.volume


def test_no_adjustment_leaves_the_row_alone() -> None:
    row = PanelRow(day=date(2020, 1, 2), symbol="X", close=10.0, volume=5.0, turnover=50.0)
    assert row.adjusted(1.0) is row


def test_a_deposit_is_not_a_daily_gain() -> None:
    days = [date(2026, 1, d) for d in (5, 6, 7)]
    result = TierBResult(
        strategy="s",
        days=days,
        # Flat book of 1,000,000; 100,000 deposited before the 7th's close.
        equity=[1_000_000.0, 1_000_000.0, 1_100_000.0],
        applied_flows=[{"amount": 100_000.0, "fill_day": days[2]}],
    )
    assert result.daily_returns() == [0.0, 0.0]
    assert abs(result.total_return) < 1e-12


def test_returns_without_flows_are_unchanged() -> None:
    days = [date(2026, 1, d) for d in (5, 6, 7)]
    result = TierBResult(strategy="s", days=days, equity=[100.0, 110.0, 99.0])
    assert result.daily_returns() == [110.0 / 100.0 - 1.0, 99.0 / 110.0 - 1.0]


# --- shorts are refused in the daily engines (T-4363) ----------------------


def _flat_panel(n_symbols: int = 4, n_days: int = 80) -> list[PanelRow]:
    from datetime import timedelta

    start = date(2024, 1, 1)
    return [
        PanelRow(
            day=start + timedelta(days=d),
            symbol=f"S{s}",
            close=100.0 * (1.0 + 0.001 * d * (s + 1)),
            volume=1000.0,
            turnover=1e9,
            isin=f"TEST{s:06d}",
        )
        for s in range(n_symbols)
        for d in range(n_days)
    ]


class _LongShort(Strategy):
    """Long S0 and S1, short S2 and S3: what a pasted pairs rule might return."""

    name = "long_short_test"

    def target_weights(self, view: MarketView) -> dict[str, float]:
        return {"S0": 0.5, "S1": 0.5, "S2": -0.5, "S3": -0.5}


class _LongOnly(Strategy):
    name = "long_only_test"

    def target_weights(self, view: MarketView) -> dict[str, float]:
        return {"S0": 0.5, "S1": 0.5}


def test_long_only_splits_longs_from_refused_shorts() -> None:
    kept, refused = long_only({"A": 0.4, "B": -0.2, "C": 0.0, "D": -0.1})
    assert kept == {"A": 0.4, "C": 0.0}
    assert refused == ["B", "D"]


def test_neither_engine_ever_holds_a_negative_quantity() -> None:
    from eulerlab.backtest import event_driven, vector

    rows = _flat_panel()
    a = vector.run(rows, _LongShort(), warmup=10, rebalance_every=20, asset_class="equity")
    b = event_driven.run(rows, _LongShort(), warmup=10, rebalance_every=20, asset_class="equity")
    assert all(f.symbol in {"S0", "S1"} for f in a.fills)
    assert b.portfolio is not None
    assert all(q >= 0 for q in b.portfolio.holdings().values())
    assert set(b.portfolio.holdings()) <= {"S0", "S1"}
    # Counted, so a report can say what was not traded: two shorts per decision.
    assert a.refused_shorts > 0
    assert a.refused_shorts == b.refused_shorts
    assert a.refused_shorts % 2 == 0


def test_a_refused_short_trades_exactly_like_leaving_it_out() -> None:
    """The longs are not rescaled up to fill the gap the shorts left: the book
    holds what it would have held with the shorts simply absent."""
    from eulerlab.backtest import event_driven, vector

    rows = _flat_panel()
    for engine in (vector, event_driven):
        mixed = engine.run(rows, _LongShort(), warmup=10, rebalance_every=20, asset_class="equity")
        plain = engine.run(rows, _LongOnly(), warmup=10, rebalance_every=20, asset_class="equity")
        assert mixed.equity == plain.equity
        assert plain.refused_shorts == 0
