"""Momentum 12-1.

Source: Jegadeesh & Titman (1993). One strategy from the published literature: its builder,
its library entry (SPEC) and its citation and coded steps (RESEARCH) are all in
this file. `docs/RESEARCH/017` holds the source URLs and fetch dates.
"""

from __future__ import annotations

from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import Strategy


def momentum_12_1(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Jegadeesh & Titman (1993). Buy 12-month winners, skipping last month.

    The skip is the point: month -1 carries the short-term reversal that
    `reversal_1m` trades in the opposite direction, and without the skip the
    two effects cancel.
    """
    return RankAndHold("momentum_12_1", top_n=top_n, min_names=min_names)


SPEC: tuple[str, str, str, str, int, list[str]] = (
    "Momentum 12-1",
    "Buy 12-month winners, skipping the last month. Jegadeesh & Titman (1993).",
    "technical",
    "cross-section",
    263,
    ["H-0001", "momentum_12_1"],
)
"""(title, summary, kind, shape, lookback, ledger subjects) for the strategy library."""

RESEARCH: tuple[str, str, str, list[str]] = (
    "Jegadeesh & Titman (1993)",
    "Winners minus losers earned about 1% a month over 1965-1989, "
    "before costs and before the crash risk later work identified.",
    "NYSE and AMEX common stocks, monthly, 1965-1989",
    [
        "Score each name by its total return from 252 trading days ago to "
        "21 days ago — twelve months, skipping the most recent one.",
        "The skip is the construction, not a detail: 12-month momentum and "
        "1-month reversal point opposite ways, so an unskipped return "
        "averages a signal with its own opposite.",
        "Sit the day out unless at least 50 names can be scored.",
        "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
        "Needs 263 days of history per name, so the first 263 days of any "
        "window produce no position at all.",
    ],
)
"""(citation, what the source reported, what the source tested, steps as coded)."""
