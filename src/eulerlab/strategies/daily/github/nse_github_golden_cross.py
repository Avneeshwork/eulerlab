"""Golden cross 50/200, liquid NSE stocks (GitHub rule).

Source: lukelebaudy/Golden-Cross-Backtester (GitHub, 2026).

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
    _closes,
    crossing_rule,
)
from eulerlab.strategies.daily.india_papers import PaperStrategy


def golden_cross_rule(rows: Sequence[PanelRow]) -> Age:
    """lukelebaudy/Golden-Cross-Backtester: buy the 50-day average crossing above
    the 200-day, sell the cross back below."""
    closes = _closes(rows)
    if len(closes) < 202:
        return None
    return crossing_rule(indicators.sma(closes, 50), indicators.sma(closes, 200), len(closes))


STRATEGIES = (
    PaperStrategy(
        "nse_github_golden_cross",
        "Golden cross 50/200, liquid NSE stocks (GitHub rule)",
        "github-2026-golden-cross-backtester",
        "lukelebaudy/Golden-Cross-Backtester (GitHub, 2026)",
        "Buy when the 50-day average crosses above the 200-day; sell at the cross back below.",
        (
            "Among the point-in-time 250 most-traded stocks. A stock is held from a golden "
            "cross to the next death cross, replayed over the last 250 sessions.",
            "Up to 20 names at a twentieth of capital each, or an equal share when more "
            "are in; filled at the next session's close.",
        ),
        200 + STATE_WINDOW + 5,
        lambda: PositionRule(
            "nse_github_golden_cross", golden_cross_rule, lookback=200 + STATE_WINDOW + 5, slots=20
        ),
    ),
)
