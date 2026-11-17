"""December only, Nifty (India).

Source: Sah (2009), NSE research paper.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from eulerlab.strategies.daily.india_papers.common import INDEX_ONLY, PaperStrategy, _calendar


def december(calendar: Sequence[date], i: int) -> bool:
    """Sah (2009): the December effect."""
    return calendar[i].month == 12


STRATEGIES = (
    PaperStrategy(
        "india_december",
        "December only, Nifty (India)",
        "sah-2009-seasonality-india",
        "Sah (2009), NSE research paper",
        "Hold NIFTYBEES in December only.",
        ("Long NIFTYBEES over every trading day in December; in cash otherwise.",),
        5,
        _calendar("india_december", december),
        "all",
        INDEX_ONLY,
    ),
)
