"""Momentum, crash-filtered.

Source: . One strategy from the published literature: its builder,
its library entry (SPEC) and its citation and coded steps (RESEARCH) are all in
this file. `docs/RESEARCH/017` holds the source URLs and fetch dates.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import Strategy
from eulerlab.strategies.daily.published.common import Composite


def momentum_quality(top_n: int = 30, min_names: int = 20) -> Strategy:
    """Momentum, filtered by not-falling-apart.

    Momentum's known failure is the crash: winners are high-beta going into a
    reversal. Averaging its rank with drawdown and volatility is the standard
    response, and whether it helps here is an empirical question nobody has
    asked of this data.
    """
    return Composite(
        ["momentum_12_1", "max_drawdown", "low_volatility"], top_n=top_n, min_names=min_names
    )


SPEC: tuple[str, str, str, str, int, list[str]] = (
    "Momentum, crash-filtered",
    "Momentum averaged with drawdown and volatility — the standard answer to momentum crashes.",
    "quant",
    "cross-section",
    263,
    ["momentum_12_1"],
)
"""(title, summary, kind, shape, lookback, ledger subjects) for the strategy library."""

RESEARCH: tuple[str, str, str, list[str]] = (
    "",
    "",
    "",
    [
        "Not from a paper. Momentum's known failure is the crash — winners "
        "are high-beta going into a reversal — and averaging its rank with "
        "drawdown and volatility is the standard response to that. Whether "
        "it helps on this data is an open question.",
        "Score each name on 12-1 momentum, negated worst 6-month drawdown, "
        "and negated 63-day return dispersion.",
        "Convert each to a percentile rank within its feature and average "
        "the three; drop names missing any of them.",
        "Sit the day out unless at least 20 names survive.",
        "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
    ],
)
"""(citation, what the source reported, what the source tested, steps as coded)."""
