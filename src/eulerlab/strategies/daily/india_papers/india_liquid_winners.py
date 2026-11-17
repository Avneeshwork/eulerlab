"""Liquid winners (India).

Source: Chui, Ranganathan, Rohit & Veeraraghavan (2023), Pacific-Basin Finance Journal
82.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers.common import (
    MONTH,
    YEAR,
    DoubleSort,
    PaperStrategy,
    momentum,
)


def median_turnover(rows: Sequence[PanelRow]) -> float | None:
    values = sorted(r.turnover for r in rows[-3 * MONTH :] if r.turnover > 0)
    return values[len(values) // 2] if len(values) >= MONTH else None


STRATEGIES = (
    PaperStrategy(
        "india_liquid_winners",
        "Liquid winners (India)",
        "chui-2023-momentum-reversals-liquidity-india",
        "Chui, Ranganathan, Rohit & Veeraraghavan (2023), Pacific-Basin Finance Journal 82",
        "Among the top 30% by 6-month return, hold the more liquid half by turnover.",
        (
            "Winners: top 30% of the point-in-time top 250 by 6-month return.",
            "Of those, hold the half with the highest median rupee turnover (the paper uses "
            "share turnover ratio; shares outstanding are not in the panel). Monthly.",
        ),
        YEAR + 5,
        lambda: DoubleSort(
            "india_liquid_winners",
            momentum(6 * MONTH, 0),
            median_turnover,
            first_fraction=0.3,
            second_fraction=0.5,
            second_low=False,
            rebalance_every=MONTH,
            lookback=YEAR + 5,
        ),
    ),
)
