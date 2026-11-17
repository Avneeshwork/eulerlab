"""Day after a holiday, Nifty (India).

Source: Lu & Patel (2016), Economics Bulletin 36(2).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from eulerlab.strategies.daily.india_papers.common import INDEX_ONLY, PaperStrategy, _calendar


def post_holiday(calendar: Sequence[date], i: int) -> bool:
    """Lu & Patel (2016): the first trading day after an exchange holiday —
    a weekday the market was shut, between the previous trading day and this."""
    if i == 0:
        return False
    previous, day = calendar[i - 1], calendar[i]
    gap = (day - previous).days
    weekdays_skipped = sum(
        1 for k in range(1, gap) if date.fromordinal(previous.toordinal() + k).weekday() < 5
    )
    return weekdays_skipped > 0


STRATEGIES = (
    PaperStrategy(
        "india_post_holiday",
        "Day after a holiday, Nifty (India)",
        "lu-2016-festivity-anomaly-india",
        "Lu & Patel (2016), Economics Bulletin 36(2)",
        "Hold NIFTYBEES over the first trading day after an exchange holiday.",
        ("Long NIFTYBEES from the close before a holiday to the close of the first day after it.",),
        5,
        _calendar("india_post_holiday", post_holiday),
        "all",
        INDEX_ONLY,
    ),
)
