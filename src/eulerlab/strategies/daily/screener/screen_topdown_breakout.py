"""52-week breakout in the top 5 sectors.

Source: George and Hwang (2004); Moskowitz and Grinblatt (1999).

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers import YEAR, PaperStrategy
from eulerlab.strategies.daily.screener.common import (
    _TOPDOWN_FUNNEL,
    SWING,
    BreakoutVolume,
    TopSectorsOnly,
)

SPECS = (
    (
        PaperStrategy(
            id="screen_topdown_breakout",
            title="52-week breakout in the top 5 sectors",
            paper="george-hwang-2004-52-week-high",
            citation="George and Hwang (2004); Moskowitz and Grinblatt (1999)",
            summary="screen_52w_breakout, only in the five sectors with the best six months; weekly.",
            logic=(_TOPDOWN_FUNNEL[0], "Then as screen_52w_breakout.", _TOPDOWN_FUNNEL[1]),
            lookback=YEAR + 30,
            build=lambda: TopSectorsOnly("screen_topdown_breakout", BreakoutVolume()),
        ),
        SWING,
    ),
)
