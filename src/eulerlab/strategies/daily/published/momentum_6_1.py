"""Momentum 6-1.

Source: Jegadeesh & Titman (1993). One strategy from the published literature: its builder,
its library entry (SPEC) and its citation and coded steps (RESEARCH) are all in
this file. `docs/RESEARCH/017` holds the source URLs and fetch dates.
"""

from __future__ import annotations

from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import Strategy


def momentum_6_1(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Jegadeesh & Titman (1993), the shorter formation window they also test."""
    return RankAndHold("momentum_6_1", top_n=top_n, min_names=min_names)


SPEC: tuple[str, str, str, str, int, list[str]] = (
    "Momentum 6-1",
    "The shorter formation window Jegadeesh & Titman (1993) also test.",
    "technical",
    "cross-section",
    158,
    ["momentum_6_1"],
)
"""(title, summary, kind, shape, lookback, ledger subjects) for the strategy library."""

RESEARCH: tuple[str, str, str, list[str]] = (
    "Jegadeesh & Titman (1993)",
    "The same paper's shorter formation window; weaker than 12-1 in their own results.",
    "NYSE and AMEX common stocks, monthly, 1965-1989",
    [
        "Score each name by its total return from 126 trading days ago to "
        "21 days ago — six months, skipping the most recent one.",
        "Sit the day out unless at least 50 names can be scored.",
        "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
        "Needs 158 days of history per name.",
    ],
)
"""(citation, what the source reported, what the source tested, steps as coded)."""
