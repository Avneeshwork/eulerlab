"""Nearest the 52-week high, top decile (India).

Source: Raju (2023), SSRN 4587697.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers.common import MONTH, YEAR, PaperStrategy, RankTop


def nearness_to_52w_high(rows: Sequence[PanelRow]) -> float | None:
    window = rows[-YEAR:]
    if len(window) < YEAR:
        return None
    high = max(r.close for r in window)
    return rows[-1].close / high if high > 0 else None


STRATEGIES = (
    PaperStrategy(
        "india_52w_high",
        "Nearest the 52-week high, top decile (India)",
        "raju-2023-52-week-high-india",
        "Raju (2023), SSRN 4587697",
        "Hold the decile of the point-in-time top 250 closest to its 52-week high, rebalanced monthly.",
        (
            "Score: today's close over the highest close of the past 52 weeks (George & Hwang).",
            "Top decile, equal-weighted, monthly. Assumed: only the abstract was readable.",
        ),
        YEAR + 5,
        lambda: RankTop(
            "india_52w_high",
            nearness_to_52w_high,
            fraction=0.1,
            highest=True,
            rebalance_every=MONTH,
            lookback=YEAR + 5,
        ),
    ),
)
