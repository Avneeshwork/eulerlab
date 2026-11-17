"""Trend pullback in the top 5 sectors.

Source: Connors RSI(2) with a 200-day trend; Moskowitz and Grinblatt (1999).

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers import PaperStrategy
from eulerlab.strategies.daily.screener.common import (
    _TOPDOWN_FUNNEL,
    SWING,
    TopSectorsOnly,
    TrendPullback,
)

SPECS = (
    (
        PaperStrategy(
            id="screen_topdown_pullback",
            title="Trend pullback in the top 5 sectors",
            paper="github-2021-connors-rsi2-bot",
            citation="Connors RSI(2) with a 200-day trend; Moskowitz and Grinblatt (1999)",
            summary="screen_trend_pullback, only in the five sectors with the best six months; weekly.",
            logic=(_TOPDOWN_FUNNEL[0], "Then as screen_trend_pullback.", _TOPDOWN_FUNNEL[1]),
            lookback=230,
            build=lambda: TopSectorsOnly("screen_topdown_pullback", TrendPullback()),
        ),
        SWING,
    ),
)
