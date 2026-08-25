"""The Sharpe that makes a sweep result comparable to the noise bar.

Everything in this platform is read against a bar expressed as a Sharpe, so a
result reported only in currency cannot be the main result no matter where it
is displayed. The subtle part is not the ratio, it is the denominator: which
sessions count.
"""

from __future__ import annotations

import datetime as dt

from eulerlab.intraday.bracket import Exit, Trade
from eulerlab.intraday.paper_scan import SignalScan
from eulerlab.intraday.tweezer import Plan

EQUITY = 1_000_000.0


def _trade(day: int, pnl: float) -> Trade:
    """A filled trade whose net P&L is `pnl`, entered on the given day."""
    entry = 100.0
    shares = 100
    plan = Plan(
        signal_ts=dt.datetime(2026, 6, day, 13, 59, tzinfo=dt.UTC),
        entry=entry,
        stop=entry - 1.0,
        target_1=entry + 1.0,
        target_2=entry + 2.0,
        r=1.0,
        shares_1=shares,
        shares_2=0,
        risk_pct=0.01,
    )
    return Trade(
        plan=plan,
        entry_ts=dt.datetime(2026, 6, day, 14, 0, tzinfo=dt.UTC),
        entry_price=entry,
        exits=[
            Exit(
                ts=dt.datetime(2026, 6, day, 15, 0, tzinfo=dt.UTC),
                price=entry + pnl / shares,
                shares=shares,
                reason="target",
            )
        ],
        costs=0.0,
    )


def test_flat_sessions_are_counted() -> None:
    """The correction that stops a rare signal reporting a borrowed Sharpe.

    A signal firing twice in 58 sessions has a very different return series
    from one trading daily. Dropping the 56 zeros would report the second's
    volatility for the first and inflate its Sharpe by roughly the square root
    of how rarely it trades.
    """
    scan = SignalScan(signal="x", symbol="Q", sessions=10)
    scan.trades = [_trade(1, 5_000.0), _trade(2, -2_000.0)]
    series = scan.session_pnl()
    assert len(series) == 10
    assert series[:2] == [5_000.0, -2_000.0]
    assert series[2:] == [0.0] * 8


def test_a_rare_signal_scores_below_a_frequent_one_with_the_same_edge() -> None:
    """Directly the consequence of counting the flat days."""
    rare = SignalScan(signal="rare", symbol="Q", sessions=20)
    rare.trades = [_trade(1, 4_000.0), _trade(2, 4_000.0)]

    # Varying, because a perfectly constant series has zero volatility and is
    # correctly refused as undefined rather than scored as infinite.
    often = SignalScan(signal="often", symbol="Q", sessions=20)
    often.trades = [_trade(day, 300.0 if day % 2 else 500.0) for day in range(1, 21)]

    rare_sharpe = rare.sharpe(EQUITY)
    often_sharpe = often.sharpe(EQUITY)
    assert rare_sharpe is not None and often_sharpe is not None
    assert often_sharpe > rare_sharpe


def test_no_variation_is_undefined_not_zero() -> None:
    """Zero is a finding — "no edge". None is the absence of one.

    A column read as evidence must not show them the same way.
    """
    scan = SignalScan(signal="x", symbol="Q", sessions=5)
    scan.trades = []
    assert scan.sharpe(EQUITY) is None


def test_a_single_session_is_undefined() -> None:
    scan = SignalScan(signal="x", symbol="Q", sessions=1)
    scan.trades = [_trade(1, 1_000.0)]
    assert scan.sharpe(EQUITY) is None


def test_losses_produce_a_negative_sharpe() -> None:
    scan = SignalScan(signal="x", symbol="Q", sessions=10)
    scan.trades = [_trade(day, -500.0) for day in range(1, 6)]
    sharpe = scan.sharpe(EQUITY)
    assert sharpe is not None
    assert sharpe < 0
