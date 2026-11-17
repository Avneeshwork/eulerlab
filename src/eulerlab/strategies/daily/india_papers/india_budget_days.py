"""Union Budget days, Nifty (India).

Source: Srinivasu & Prathyusha (2025), International Journal of Economics and Business
Administration 23(1).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from datetime import date, timedelta

from eulerlab.strategies.daily.india_papers.common import INDEX_ONLY, PaperStrategy, _calendar

UNION_BUDGETS = (
    date(2016, 2, 29),
    date(2017, 2, 1),
    date(2018, 2, 1),
    date(2019, 2, 1),
    date(2019, 7, 5),
    date(2020, 2, 1),
    date(2021, 2, 1),
    date(2022, 2, 1),
    date(2023, 2, 1),
    date(2024, 2, 1),
    date(2024, 7, 23),
    date(2025, 2, 1),
    date(2026, 2, 1),
)
"""Union Budget presentation days, interim budgets included. # ASSUMPTION: A-042."""


def around_budget(calendar: Sequence[date], i: int) -> bool:
    """Days -1, 0 and +1 around each Union Budget. A budget on a day the market
    did not trade counts from the next trading day."""
    for budget in UNION_BUDGETS:
        event = bisect_right(calendar, budget - timedelta(days=1))
        if event < len(calendar) and event - 1 <= i <= event + 1:
            return True
    return False


STRATEGIES = (
    PaperStrategy(
        "india_budget_days",
        "Union Budget days, Nifty (India)",
        "srinivasu-2025-union-budget-india",
        "Srinivasu & Prathyusha (2025), International Journal of Economics and Business Administration 23(1)",
        "Hold NIFTYBEES over the day before, the day of, and the day after each Union Budget.",
        (
            "Long NIFTYBEES over trading days -1, 0 and +1 around each Union Budget, interim included.",
        ),
        5,
        _calendar("india_budget_days", around_budget),
        "all",
        INDEX_ONLY,
    ),
)
