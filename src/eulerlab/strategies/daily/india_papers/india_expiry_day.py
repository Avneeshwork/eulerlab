"""Monthly expiry day, Nifty (India).

Source: Singh & Shaik (2020), International Journal of Economics and Financial Issues
10(3).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from datetime import date

from eulerlab.strategies.daily.india_papers.common import INDEX_ONLY, PaperStrategy, _calendar


def _expiry_weekday(day: date) -> int:
    """Nifty monthly expiry: last Thursday, moved to last Tuesday from
    September 2025 (NSE circular FAOP68747)."""
    return 1 if day >= date(2025, 9, 1) else 3


def is_monthly_expiry(calendar: Sequence[date], i: int) -> bool:
    """The month's expiry: the last trading day on or before the month's last
    expiry weekday, since a holiday moves expiry to the previous trading day."""
    import calendar as cal

    from eulerlab.market_history import nifty_expiries

    day = calendar[i]
    # The real expiry dates, read from the F&O bhavcopies, when they have been
    # built (`make market-history`); the weekday rule below is the fallback.
    known = nifty_expiries()
    if known and known[0] <= day <= known[-1]:
        return day in set(known)
    weekday = _expiry_weekday(day)
    last = date(day.year, day.month, cal.monthrange(day.year, day.month)[1])
    while last.weekday() != weekday:
        last = date.fromordinal(last.toordinal() - 1)
    position = bisect_right(calendar, last) - 1
    return position == i


STRATEGIES = (
    PaperStrategy(
        "india_expiry_day",
        "Monthly expiry day, Nifty (India)",
        "singh-2020-expiry-effects-india",
        "Singh & Shaik (2020), International Journal of Economics and Financial Issues 10(3)",
        "Hold NIFTYBEES over the monthly F&O expiry day only.",
        (
            "Expiry: the last Thursday of the month (last Tuesday from September 2025), "
            "or the trading day before when that is a holiday.",
            "Long NIFTYBEES from the previous close to the expiry close. The paper found "
            "no significant return effect; this measures whether one exists here.",
        ),
        5,
        _calendar("india_expiry_day", is_monthly_expiry),
        "all",
        INDEX_ONLY,
    ),
)
