"""Low-volatility anomaly.

Source: Baker, Bradley & Wurgler (2011). One strategy from the published literature: its builder,
its library entry (SPEC) and its citation and coded steps (RESEARCH) are all in
this file. `docs/RESEARCH/017` holds the source URLs and fetch dates.
"""

from __future__ import annotations

from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import Strategy


def low_volatility(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Baker, Bradley & Wurgler (2011). Low-volatility stocks outperformed.

    The opposite of what risk pricing predicts, over 41 years of US data.
    """
    return RankAndHold("low_volatility", top_n=top_n, min_names=min_names)


SPEC: tuple[str, str, str, str, int, list[str]] = (
    "Low-volatility anomaly",
    "Low-volatility stocks outperformed over 41 years. Baker, Bradley & Wurgler (2011).",
    "quant",
    "cross-section",
    73,
    ["low_volatility"],
)
"""(title, summary, kind, shape, lookback, ledger subjects) for the strategy library."""

RESEARCH: tuple[str, str, str, list[str]] = (
    "Baker, Bradley & Wurgler (2011)",
    "The lowest-volatility quintile beat the highest over 1968-2008, "
    "which is the opposite of what a risk premium predicts.",
    "US equities, monthly, 1968-2008",
    [
        "Score each name by the median absolute deviation of its daily "
        "returns over the last 63 trading days, negated — quietest ranks "
        "highest.",
        "Median absolute deviation rather than standard deviation: one "
        "spike dominates a stdev, so the score would describe a single day "
        "rather than the stock.",
        "Needs at least 20 usable returns, or the name is unscored.",
        "Sit the day out unless at least 50 names can be scored.",
        "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
    ],
)
"""(citation, what the source reported, what the source tested, steps as coded)."""
