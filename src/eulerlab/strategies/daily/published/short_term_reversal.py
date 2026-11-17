"""Short-term reversal.

Source: Jegadeesh (1990). One strategy from the published literature: its builder,
its library entry (SPEC) and its citation and coded steps (RESEARCH) are all in
this file. `docs/RESEARCH/017` holds the source URLs and fetch dates.
"""

from __future__ import annotations

from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import Strategy


def short_term_reversal(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Jegadeesh (1990), Lehmann (1990). Last month's losers outperform.

    `reversal_1m` is already negated in the library, so ranking it high is
    buying the losers — the sign convention that every feature is oriented so
    higher is better.
    """
    return RankAndHold("reversal_1m", top_n=top_n, min_names=min_names)


SPEC: tuple[str, str, str, str, int, list[str]] = (
    "Short-term reversal",
    "Last month's losers outperform. Jegadeesh (1990), Lehmann (1990).",
    "technical",
    "cross-section",
    32,
    ["reversal_1m"],
)
"""(title, summary, kind, shape, lookback, ledger subjects) for the strategy library."""

RESEARCH: tuple[str, str, str, list[str]] = (
    "Jegadeesh (1990)",
    "Last month's losers outperformed last month's winners over 1934-1987 "
    "— the opposite sign to momentum at a longer horizon.",
    "NYSE common stocks, monthly, 1934-1987",
    [
        "Score each name by its last 21 trading days' return, negated, so "
        "the worst recent performer ranks highest.",
        "Sit the day out unless at least 50 names can be scored.",
        "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
        "Needs 32 days of history per name.",
    ],
)
"""(citation, what the source reported, what the source tested, steps as coded)."""
