"""Reversal, liquidity-filtered.

Source: . One strategy from the published literature: its builder,
its library entry (SPEC) and its citation and coded steps (RESEARCH) are all in
this file. `docs/RESEARCH/017` holds the source URLs and fetch dates.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import Strategy
from eulerlab.strategies.daily.published.common import Composite


def value_reversal(top_n: int = 30, min_names: int = 20) -> Strategy:
    """Short-term reversal combined with liquidity.

    Reversal is strongest in illiquid names and most expensive to trade there,
    which is the tension this pairing exposes rather than resolves.
    """
    return Composite(["reversal_1m", "turnover_liquidity"], top_n=top_n, min_names=min_names)


SPEC: tuple[str, str, str, str, int, list[str]] = (
    "Reversal, liquidity-filtered",
    "Reversal is strongest where it is most expensive to trade. This pairing exposes that.",
    "quant",
    "cross-section",
    73,
    ["reversal_1m"],
)
"""(title, summary, kind, shape, lookback, ledger subjects) for the strategy library."""

RESEARCH: tuple[str, str, str, list[str]] = (
    "",
    "",
    "",
    [
        "Not from a paper. Reversal is strongest in illiquid names and most "
        "expensive to trade there; this pairing exposes that tension rather "
        "than resolving it.",
        "Score each name on negated 21-day return and on log median turnover over 63 days.",
        "Convert each to a percentile rank within its feature and average "
        "the two; drop names missing either.",
        "Sit the day out unless at least 20 names survive.",
        "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
    ],
)
"""(citation, what the source reported, what the source tested, steps as coded)."""
