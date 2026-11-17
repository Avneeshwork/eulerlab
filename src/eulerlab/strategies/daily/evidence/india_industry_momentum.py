"""Industry momentum, top three industries (India).

Source: Moskowitz & Grinblatt (1999), JF 54(4).

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import statistics

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.evidence.common import _equal
from eulerlab.strategies.daily.india_papers import MONTH, PaperStrategy, liquid_universe


def industries() -> dict[str, str]:
    """Symbol to industry (level 2 of NSE's classification), as it stands today.

    ASSUMPTION: A-061 — today's industry stands for the past; companies rarely
    change industry, but a few have, and the backtest cannot see when.
    """
    from eulerlab.features import company

    return {symbol: c.industry for symbol, c in company.load_digest().items() if c.industry}


class IndustryMomentum(Strategy):
    """Each month, the liquid members of the three industries with the best
    six-month equal-weight return (Moskowitz & Grinblatt 1999). Industries
    need three liquid members to be ranked."""

    def __init__(self, name: str, *, top: int = 3, members: int = 3) -> None:
        self.name = name
        self.top = top
        self.members = members
        self.rebalance_every = MONTH
        self.lookback = 6 * MONTH + 10
        self._industries: dict[str, str] | None = None

    def target_weights(self, view: MarketView) -> dict[str, float]:
        if self._industries is None:
            self._industries = industries()
        groups: dict[str, list[tuple[str, float]]] = {}
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            industry = self._industries.get(symbol)
            if industry is None or len(rows) <= 6 * MONTH or rows[-1 - 6 * MONTH].close <= 0:
                continue
            past = rows[-1].close / rows[-1 - 6 * MONTH].close - 1.0
            groups.setdefault(industry, []).append((symbol, past))
        ranked = sorted(
            (
                (statistics.fmean(p for _, p in members), industry)
                for industry, members in groups.items()
                if len(members) >= self.members
            ),
            key=lambda x: (-x[0], x[1]),
        )
        chosen = [s for _, industry in ranked[: self.top] for s, _ in groups[industry]]
        return _equal(sorted(chosen))


STRATEGIES = (
    PaperStrategy(
        "india_industry_momentum",
        "Industry momentum, top three industries (India)",
        "moskowitz-grinblatt-1999-industry-momentum",
        "Moskowitz & Grinblatt (1999), JF 54(4)",
        "Each month, hold the liquid stocks of the three industries with the best six-month return.",
        (
            "Industries: level 2 of NSE's classification (39 industries) as it stands today, "
            "applied to the past (A-061). An industry needs three liquid members.",
            "Six-month equal-weight industry return, monthly, members equal-weighted. No Indian "
            "test of industry momentum was found; stock momentum in India is well documented.",
        ),
        6 * MONTH + 10,
        lambda: IndustryMomentum("india_industry_momentum"),
    ),
)
