"""Backtester fixes from the 2026-11-01 line-by-line review (HISTORY #53)."""

from __future__ import annotations

from datetime import date

from eulerlab.backtest.event_driven import TierBResult
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
