"""High-volume return premium, held four weeks (India).

Source: Kaniel, Ozoguz & Starks (2012), JFE 103(2); Gervais, Kaniel & Mingelgrin (2001),
JF 56(3).

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.evidence.common import HOLD, WEEK
from eulerlab.strategies.daily.india_papers import PaperStrategy, liquid_universe

REFERENCE_WEEKS = 10
HOLD_WEEKS = 4


def high_volume_week(rows: Sequence[PanelRow], weeks_ago: int) -> bool:
    """Kaniel, Ozoguz & Starks: the week's volume is the highest of itself and the
    ten weeks before it (top decile of eleven). Rupee turnover, not shares, so a
    split cannot look like a volume spike."""
    end = len(rows) - weeks_ago * WEEK
    start = end - (REFERENCE_WEEKS + 1) * WEEK
    if start < 0:
        return False
    weekly = [
        sum(r.turnover for r in rows[start + k * WEEK : start + (k + 1) * WEEK])
        for k in range(REFERENCE_WEEKS + 1)
    ]
    return weekly[-1] > 0 and weekly[-1] > max(weekly[:-1])


class HighVolumePremium(Strategy):
    """Hold a stock for four weeks after a week of unusually high volume.

    Weekly decisions, up to `HOLD` names at 1/`HOLD` each (an equal share when
    more qualify). Gervais, Kaniel & Mingelgrin (2001) measured the premium
    over the following weeks; four is the month the house holds for.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = WEEK
        self.lookback = (REFERENCE_WEEKS + HOLD_WEEKS + 2) * WEEK + 60
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        # Fixed 1/HOLD weights, the earliest-flagged kept when more qualify: an
        # equal share of every flagged stock re-sized them all each week
        # (research 113, 2026-10-18).
        flagged: list[tuple[int, str]] = []
        for symbol in liquid_universe(view):
            weeks = [w for w in range(HOLD_WEEKS) if high_volume_week(view.history[symbol], w)]
            if weeks:
                flagged.append((max(weeks), symbol))
        flagged.sort(key=lambda x: (-x[0], x[1]))
        return {s: 1.0 / HOLD for _, s in flagged[:HOLD]}


STRATEGIES = (
    PaperStrategy(
        "india_high_volume_premium",
        "High-volume return premium, held four weeks (India)",
        "kaniel-ozoguz-starks-2012-high-volume-premium",
        "Kaniel, Ozoguz & Starks (2012), JFE 103(2); Gervais, Kaniel & Mingelgrin (2001), JF 56(3)",
        "Buy stocks whose weekly turnover is the highest of their last eleven weeks; hold four weeks.",
        (
            "A high-volume week: rupee turnover above every one of the ten weeks before it. "
            "Found in 41 countries, developed and emerging, and not a risk or liquidity effect.",
            "Weekly decisions, up to 30 names, point-in-time 250 most-traded. Long only.",
        ),
        (REFERENCE_WEEKS + HOLD_WEEKS + 2) * WEEK + 60,
        lambda: HighVolumePremium("india_high_volume_premium"),
    ),
)
