"""Connors RSI(2), daily, liquid NSE stocks (GitHub rule).

Source: leo-aa88/larry_connors_rsi2_bot (GitHub, 2021).

One daily rule from a public GitHub repository. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.features import indicators
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.github.common import (
    STATE_WINDOW,
    Age,
    PositionRule,
    _age,
    _closes,
    in_trade,
)
from eulerlab.strategies.daily.india_papers import PaperStrategy


def rsi2_rule(rows: Sequence[PanelRow]) -> Age:
    """leo-aa88/larry_connors_rsi2_bot: above the 200-day average, in when RSI(2) < 5,
    out when the close is above the 5-day average."""
    closes = _closes(rows)
    n = len(closes)
    if n < 200 + 2:
        return None
    sma200, sma5, rsi2 = (
        indicators.sma(closes, 200),
        indicators.sma(closes, 5),
        indicators.rsi(closes, 2),
    )

    def enter(i: int) -> bool:
        trend, value = sma200[i], rsi2[i]
        return trend is not None and value is not None and closes[i] > trend and value < 5

    def leave(i: int) -> bool:
        short = sma5[i]
        return short is not None and closes[i] > short

    return _age(n, in_trade(n, enter, leave, start=max(200, n - STATE_WINDOW)))


STRATEGIES = (
    PaperStrategy(
        "nse_github_rsi2_daily",
        "Connors RSI(2), daily, liquid NSE stocks (GitHub rule)",
        "github-2021-connors-rsi2-bot",
        "leo-aa88/larry_connors_rsi2_bot (GitHub, 2021)",
        "Above the 200-day average, buy when RSI(2) is under 5; sell when the close is back above the 5-day average.",
        (
            "Among the point-in-time 250 most-traded stocks: in when close > SMA(200) and "
            "RSI(2) < 5, out when close > SMA(5). The repository runs the rule on 15-minute "
            "crypto bars; Connors wrote it for daily stocks, which is what is run here.",
            "Up to 10 names at a tenth of capital each; filled at the next session's close.",
        ),
        200 + STATE_WINDOW + 5,
        lambda: PositionRule(
            "nse_github_rsi2_daily", rsi2_rule, lookback=200 + STATE_WINDOW + 5, slots=10
        ),
    ),
)
