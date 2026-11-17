"""52-week breakout.

Source: George and Hwang (2004), with a volume filter.

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers import YEAR, PaperStrategy
from eulerlab.strategies.daily.screener.common import SWING, BreakoutVolume

SPECS = (
    (
        PaperStrategy(
            id="screen_52w_breakout",
            title="52-week breakout",
            paper="george-hwang-2004-52-week-high",
            citation="George and Hwang (2004), with a volume filter",
            summary="Weekly: a close at a new 52-week high on twice the usual volume in the last 20 sessions.",
            logic=(
                "Close at or above the prior 251-session high.",
                "Volume at least twice its 50-session median.",
                "Decided weekly; held while the breakout is within 20 sessions.",
                "A tenth of capital each, or equal shares when more qualify.",
            ),
            lookback=YEAR + 30,
            build=BreakoutVolume,
        ),
        SWING,
    ),
)
