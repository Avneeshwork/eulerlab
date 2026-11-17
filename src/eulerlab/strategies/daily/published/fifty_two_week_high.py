"""52-week high.

Source: George & Hwang (2004). One strategy from the published literature: its builder,
its library entry (SPEC) and its citation and coded steps (RESEARCH) are all in
this file. `docs/RESEARCH/017` holds the source URLs and fetch dates.
"""

from __future__ import annotations

from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import Strategy


def fifty_two_week_high(top_n: int = 30, min_names: int = 50) -> Strategy:
    """George & Hwang (2004). Nearness to the 52-week high forecasts returns.

    Distinct from momentum and, in the paper, dominating it — and unlike
    momentum its forecasts do not reverse over the long run.
    """
    return RankAndHold("price_to_52w_high", top_n=top_n, min_names=min_names)


SPEC: tuple[str, str, str, str, int, list[str]] = (
    "52-week high",
    "Nearness to the 52-week high forecasts returns, and does not reverse. George & Hwang (2004).",
    "technical",
    "cross-section",
    210,
    ["price_to_52w_high"],
)
"""(title, summary, kind, shape, lookback, ledger subjects) for the strategy library."""

RESEARCH: tuple[str, str, str, list[str]] = (
    "George & Hwang (2004)",
    "Nearness to the 52-week high forecast returns and, unlike momentum, "
    "the forecasts did not reverse over the long run.",
    "US equities, monthly, 1963-2001",
    [
        "Score each name by its last close divided by the highest close in "
        "the last 252 trading days — 1.0 means sitting at its 52-week high.",
        "Needs at least 200 rows in that window, or the name is unscored.",
        "Sit the day out unless at least 50 names can be scored.",
        "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
    ],
)
"""(citation, what the source reported, what the source tested, steps as coded)."""
