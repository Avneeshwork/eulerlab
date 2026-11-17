"""Size effect.

Source: Banz (1981). One strategy from the published literature: its builder,
its library entry (SPEC) and its citation and coded steps (RESEARCH) are all in
this file. `docs/RESEARCH/017` holds the source URLs and fetch dates.
"""

from __future__ import annotations

from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import Strategy


def small_size(top_n: int = 30, min_names: int = 50) -> Strategy:
    """Banz (1981). Small firms outearned large ones.

    `small_size` is negated log price, which is a **weak proxy** for market
    capitalisation — the library says so. A low price is not a small company.
    Registered because the effect is real in the literature; the implementation
    is the honest limit of what the panel supports.
    """
    return RankAndHold("small_size", top_n=top_n, min_names=min_names)


SPEC: tuple[str, str, str, str, int, list[str]] = (
    "Size effect",
    "Small firms outearned large. Banz (1981). Proxied by negated log price, which is weak.",
    "fundamental",
    "cross-section",
    11,
    ["small_size"],
)
"""(title, summary, kind, shape, lookback, ledger subjects) for the strategy library."""

RESEARCH: tuple[str, str, str, list[str]] = (
    "Banz (1981)",
    "Small firms outearned large ones over 1936-1975 after adjusting for beta.",
    "NYSE common stocks, 1936-1975",
    [
        "Score each name by the negated log of its last close, so a low-priced name ranks highest.",
        "This is a weak proxy and is here to be measured, not believed: "
        "size is price times shares outstanding, and the share count is "
        "not in the bhavcopy. A low price is not a small company — it is "
        "often a normal one after a split.",
        "Sit the day out unless at least 50 names can be scored.",
        "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
    ],
)
"""(citation, what the source reported, what the source tested, steps as coded)."""
