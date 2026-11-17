"""Low lottery score, MAX(L5) (India).

Source: Sehgal, Vasishth & Deisting (2024), Borsa Istanbul Review 24(3).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers.common import MONTH, PaperStrategy, RankTop, _returns


def max_last5(rows: Sequence[PanelRow]) -> float | None:
    """MAX(L5): the largest daily return in the last 5 trading days of the
    previous month (Sehgal, Vasishth & Deisting 2024). Needs 3 of the 5."""
    if len(rows) < 30:
        return None
    this_month = (rows[-1].day.year, rows[-1].day.month)
    end = len(rows)
    while end > 0 and (rows[end - 1].day.year, rows[end - 1].day.month) == this_month:
        end -= 1
    window = rows[max(0, end - 6) : end]
    rets = _returns(window)
    return max(rets) if len(rets) >= 3 else None


STRATEGIES = (
    PaperStrategy(
        "india_low_max_l5",
        "Low lottery score, MAX(L5) (India)",
        "sehgal-2024-lottery-factor-india",
        "Sehgal, Vasishth & Deisting (2024), Borsa Istanbul Review 24(3)",
        "Hold the decile of the point-in-time top 250 with the smallest best day in the last 5 sessions of last month.",
        (
            "MAX(L5): the largest daily return in the last 5 trading days of the previous month.",
            "Each month, hold the lowest decile, equal-weighted (the paper value-weights). "
            "Long only, as the authors themselves suggest for India.",
        ),
        2 * MONTH,
        lambda: RankTop(
            "india_low_max_l5",
            max_last5,
            fraction=0.1,
            highest=False,
            rebalance_every=MONTH,
            lookback=2 * MONTH,
        ),
    ),
)
