"""The arithmetic every intraday screen shares (`intraday/screen_common.py`)."""

from __future__ import annotations

from datetime import date

import pytest

from eulerlab.costs.schedule import Side
from eulerlab.intraday import screen_common as sc


def test_daily_stats_compounds_and_measures_the_worst_drawdown() -> None:
    stats = sc.daily_stats([0.10, -0.50, 0.20])

    assert stats["days"] == 3
    assert stats["total_return"] == pytest.approx(1.1 * 0.5 * 1.2 - 1.0)
    assert stats["max_drawdown"] == pytest.approx(-0.5)
    assert stats["sharpe"] is not None


@pytest.mark.parametrize("values", [[], [0.01], [0.002, 0.002]])
def test_daily_stats_has_no_sharpe_without_variation(values: list[float]) -> None:
    assert sc.daily_stats(values)["sharpe"] is None


def test_ema_is_seeded_at_the_first_value() -> None:
    assert sc.ema([10.0, 10.0, 10.0], 5) == [10.0, 10.0, 10.0]
    assert sc.ema([0.0, 3.0], 2) == [0.0, 2.0]


def test_rsi_waits_for_a_full_period_then_reads_one_sided_moves() -> None:
    rising = sc.rsi([1.0, 2.0, 3.0, 4.0], 2)
    flat = sc.rsi([5.0, 5.0, 5.0], 2)

    assert rising[:2] == [None, None]
    assert rising[2:] == [100.0, 100.0]
    assert flat[2] == 50.0


def test_round_trip_cost_is_both_fills_plus_slippage_on_both() -> None:
    day = date(2024, 6, 3)
    fees = sc.intraday_fee(100.0, 10, Side.BUY, day) + sc.intraday_fee(101.0, 10, Side.SELL, day)

    cost = sc.round_trip_cost(100.0, 101.0, 10, day, 1, slippage_bps=2.0)

    assert cost == pytest.approx(fees + (100.0 + 101.0) * 10 * 2.0 / 10_000.0)
    assert sc.round_trip_cost(100.0, 101.0, 10, day, 1, slippage_bps=0.0) == pytest.approx(fees)
