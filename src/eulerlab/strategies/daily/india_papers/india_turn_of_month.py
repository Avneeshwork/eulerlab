"""Turn of the month, Nifty (India).

Source: Maher & Parikh (2013), International Review of Financial Analysis 28.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from eulerlab.strategies.daily.india_papers.common import INDEX_ONLY, PaperStrategy, _calendar


def turn_of_month(calendar: Sequence[date], i: int) -> bool:
    """Days -1 to +2 around the month end: the last trading day of the month
    and the first two of the next (Maher & Parikh 2013, window unverified)."""
    day = calendar[i]
    next_day = calendar[i + 1] if i + 1 < len(calendar) else None
    if next_day is not None and next_day.month != day.month:
        return True
    first = i
    while first > 0 and calendar[first - 1].month == day.month:
        first -= 1
    # A month the calendar does not see the start of has no known first days.
    return first > 0 and i - first < 2


STRATEGIES = (
    PaperStrategy(
        "india_turn_of_month",
        "Turn of the month, Nifty (India)",
        "maher-2013-turn-of-month-india",
        "Maher & Parikh (2013), International Review of Financial Analysis 28",
        "Hold NIFTYBEES over the last trading day of each month and the first two of the next.",
        (
            "Long NIFTYBEES over trading days -1, +1 and +2 around the month end.",
            "The window is unverified: only the abstract could be read.",
        ),
        5,
        _calendar("india_turn_of_month", turn_of_month),
        "all",
        INDEX_ONLY,
    ),
)
