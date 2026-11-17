"""Monday and Wednesday, Nifty (India).

Source: Srinivasan & Kalaivani (2013), MPRA 46805.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from eulerlab.strategies.daily.india_papers.common import INDEX_ONLY, PaperStrategy, _calendar


def monday_or_wednesday(calendar: Sequence[date], i: int) -> bool:
    """Srinivasan & Kalaivani (2013): positive Monday and Wednesday returns."""
    return calendar[i].weekday() in (0, 2)


STRATEGIES = (
    PaperStrategy(
        "india_monday_wednesday",
        "Monday and Wednesday, Nifty (India)",
        "srinivasan-2013-day-of-week-india",
        "Srinivasan & Kalaivani (2013), MPRA 46805",
        "Hold NIFTYBEES over Mondays and Wednesdays only.",
        ("Long NIFTYBEES from the previous close to the Monday close and to the Wednesday close.",),
        5,
        _calendar("india_monday_wednesday", monday_or_wednesday),
        "all",
        INDEX_ONLY,
    ),
)
