"""Physical momentum, return over volatility (India).

Source: Tripurana & Devulapally (2023), arXiv:2302.13245.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers.common import (
    LIQUID_TOP,
    MONTH,
    PaperStrategy,
    RankTop,
    Score,
    _sd,
)


def mean_over_sd(days: int) -> Score:
    """Mean daily log return over its standard deviation (physical momentum's
    inverse-volatility p3, Tripurana & Devulapally 2023)."""

    def score(rows: Sequence[PanelRow]) -> float | None:
        window = rows[-days - 1 :]
        rets = [
            math.log(b.close / a.close) for a, b in pairwise(window) if a.close > 0 and b.close > 0
        ]
        sd = _sd(rets)
        return (sum(rets) / len(rets)) / sd if sd and len(rets) >= days // 2 else None

    return score


STRATEGIES = (
    PaperStrategy(
        "india_physical_momentum",
        "Physical momentum, return over volatility (India)",
        "tripurana-2023-physical-momentum-india",
        "Tripurana & Devulapally (2023), arXiv:2302.13245",
        "Hold the 10 stocks of the point-in-time top 250 with the best 6-month mean-over-volatility of daily returns, for 2 months.",
        (
            "Score: mean daily log return over 6 months divided by its standard deviation "
            "(the paper's inverse-volatility p3).",
            "Hold the top 10, equal-weighted, re-formed every 2 months (the paper's best "
            "monthly cell is 6-2). The turnover-weighted variants need shares outstanding.",
        ),
        7 * MONTH,
        lambda: RankTop(
            "india_physical_momentum",
            mean_over_sd(6 * MONTH),
            fraction=10 / LIQUID_TOP,
            highest=True,
            rebalance_every=2 * MONTH,
            lookback=7 * MONTH,
        ),
    ),
)
