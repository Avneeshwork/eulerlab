"""Illiquidity premium.

Source: Amihud (2002). One strategy from the published literature: its builder,
its library entry (SPEC) and its citation and coded steps (RESEARCH) are all in
this file. `docs/RESEARCH/017` holds the source URLs and fetch dates.
"""

from __future__ import annotations

from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import Strategy


def illiquidity_premium(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Amihud (2002). Illiquid stocks earn a premium for being illiquid.

    The one on this list most likely to be an artefact *here*: T-907 records
    that market impact is not modelled at all, so a backtest of an illiquidity
    premium is being paid the premium without paying its cost.
    """
    return RankAndHold("illiquidity_amihud", top_n=top_n, min_names=min_names)


SPEC: tuple[str, str, str, str, int, list[str]] = (
    "Illiquidity premium",
    "Illiquid stocks earn a premium. Amihud (2002). Market impact is NOT modelled here (T-907).",
    "quant",
    "cross-section",
    73,
    ["illiquidity_amihud"],
)
"""(title, summary, kind, shape, lookback, ledger subjects) for the strategy library."""

RESEARCH: tuple[str, str, str, list[str]] = (
    "Amihud (2002)",
    "Illiquid stocks earned a premium for being illiquid, over 1964-1997.",
    "NYSE common stocks, 1964-1997",
    [
        "Score each name by the median of |daily return| / turnover over "
        "the last 63 trading days, negated.",
        "The negation makes the *most liquid* name score highest, and the "
        "engine holds the highest — so as coded this buys the most liquid "
        "names, which is the opposite end from the premium Amihud "
        "measured. Recorded as S-032; not silently flipped, because "
        "turning it round changes what the strategy trades.",
        "Sit the day out unless at least 50 names can be scored.",
        "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
        "Market impact is not modelled anywhere in this engine, so a real "
        "illiquidity premium would be collected here without paying the "
        "cost that is the whole reason it exists.",
    ],
)
"""(citation, what the source reported, what the source tested, steps as coded)."""
