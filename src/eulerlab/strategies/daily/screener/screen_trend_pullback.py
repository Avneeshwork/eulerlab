"""Trend pullback.

Source: Connors RSI(2) with a 200-day trend filter.

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers import PaperStrategy
from eulerlab.strategies.daily.screener.common import SWING, TrendPullback

SPECS = (
    (
        PaperStrategy(
            id="screen_trend_pullback",
            title="Trend pullback",
            paper="github-2021-connors-rsi2-bot",
            citation="Connors RSI(2) with a 200-day trend filter",
            summary="Weekly: RSI(2) under 10 above a rising 200-day trend; out above 70 or after 10 sessions.",
            logic=(
                "Close above the 200-day average and the 50-day above the 200-day.",
                "Decided weekly: hold a stock whose RSI(2) closed under 10 in the last 10 sessions",
                "and has not closed above 70 since.",
                "Each position is a tenth of capital, or equal shares when more qualify.",
            ),
            lookback=230,
            build=TrendPullback,
        ),
        SWING,
    ),
)
