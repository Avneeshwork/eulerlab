"""Quality composite.

Source: . One strategy from the published literature: its builder,
its library entry (SPEC) and its citation and coded steps (RESEARCH) are all in
this file. `docs/RESEARCH/017` holds the source URLs and fetch dates.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import Strategy
from eulerlab.strategies.daily.published.common import Composite


def quality_composite(top_n: int = 30, min_names: int = 20) -> Strategy:
    """Low volatility, shallow drawdowns, and liquidity, ranked together.

    Not from one paper. The construction is standard and the components each
    have their own; combining them is the part that is ours, and it is exactly
    the kind of choice that should be counted as search rather than presented
    as a finding.
    """
    return Composite(
        ["low_volatility", "max_drawdown", "turnover_liquidity"], top_n=top_n, min_names=min_names
    )


SPEC: tuple[str, str, str, str, int, list[str]] = (
    "Quality composite",
    "Low volatility, shallow drawdowns and liquidity ranked together. No single paper.",
    "quant",
    "cross-section",
    136,
    [],
)
"""(title, summary, kind, shape, lookback, ledger subjects) for the strategy library."""

RESEARCH: tuple[str, str, str, list[str]] = (
    "",
    "",
    "",
    [
        "Not from a paper. The three components each have their own "
        "literature; combining them is a choice made here, and it is the "
        "kind of choice the trial ledger exists to count.",
        "Score each name three times — negated return dispersion over 63 "
        "days, negated worst 6-month drawdown, and log median turnover "
        "over 63 days.",
        "Convert each score to a within-feature percentile rank, then average the three.",
        "Drop any name not scored by all three: a name ranked on two "
        "features is not comparable to one ranked on three.",
        "Sit the day out unless at least 20 names survive.",
        "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
    ],
)
"""(citation, what the source reported, what the source tested, steps as coded)."""
