"""`make full-history`: the gate's strategies over every year held (ADR-143)."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.intraday import cross_section as cs
from eulerlab.research import full_history as fh

END = date(2026, 10, 17)


def test_recommended_settings_follow_the_data_each_strategy_needs() -> None:
    daily = fh.recommended("H-0020", END)
    minute = fh.recommended("H-0096", END)
    assert daily["start"] == "2016-01-01" and daily["timeframe"] == "1d"
    assert minute["start"] == "2021-08-20" and minute["timeframe"] == "1m"
    assert fh.recommended("H-0098", END)["timeframe"] == "1d"  # daily bars from 2016
    assert fh.recommended("H-0065", END)["capital"] == 8_000_000.0
    assert daily["end"] == minute["end"] == "2026-10-17"


def test_summary_reads_sharpe_drawdown_and_each_year() -> None:
    days = [date(2024, 12, 30) + timedelta(days=i) for i in range(5)]
    equity = [100.0, 101.0, 99.0, 102.0, 103.0]
    found = fh.summarise(days, equity)
    assert found["total_return"] == 0.03
    assert round(found["max_drawdown"], 4) == round(99.0 / 101.0 - 1.0, 4)
    assert set(found["net_by_year"]) == {"2024", "2025"}
    assert found["first"] == "2024-12-30" and found["last"] == "2025-01-03"


def test_the_curve_adds_each_days_net_pnl_and_holds_flat_days() -> None:
    day = date(2025, 1, 2)
    trade = cs.Trade("A", day, -1, 100, 5, 100.0, 355, 99.0, "time_exit")
    days, equity = fh.curve_from_trades([trade], [day - timedelta(days=1), day], 1_000_000.0)
    assert equity[0] == 1_000_000.0
    assert equity[1] == 1_000_000.0 + trade.gross - trade.costs
    assert len(days) == 2


def test_nothing_runs_without_recording_the_holdout_read() -> None:
    import inspect

    assert "record_holdout_read" in inspect.getsource(fh.run)
