"""Today's holdings run through the last `WINDOW` trading days: one profit and loss per past day."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from itertools import pairwise

from eulerlab.risk.book.common import WINDOW
from eulerlab.risk.book.holdings import Book, GapRule

# --- the book run through history ---------------------------------------------------


def window_days(prices: Mapping[str, Mapping[date, float]], window: int = WINDOW) -> list[date]:
    """The last `window + 1` days on which the market traded, oldest first."""
    days = sorted({day for series in prices.values() for day in series})
    return days[-(window + 1) :]


def returns_of(series: Mapping[date, float], days: Sequence[date]) -> list[float | None]:
    """Day-on-day returns over `days`; None where either close is missing."""
    out: list[float | None] = []
    for before, after in pairwise(days):
        a, b = series.get(before), series.get(after)
        out.append(b / a - 1 if a and b and a > 0 else None)
    return out


def scenario_pnl(
    book: Book, prices: Mapping[str, Mapping[date, float]], days: Sequence[date]
) -> tuple[list[float], float]:
    """(rupees a day, share of the holdings' value that has a full history).

    Each past day's return is applied to today's rupee value in each name. A
    name with no price on a day is flat that day.
    """
    pnl = [0.0] * max(len(days) - 1, 0)
    invested = sum(abs(h.value) for h in book.holdings)
    covered = 0.0
    for holding in book.holdings:
        moves = returns_of(prices.get(holding.symbol, {}), days)
        known = sum(1 for move in moves if move is not None)
        if moves and known == len(moves):
            covered += abs(holding.value)
        for index, move in enumerate(moves):
            if move is not None:
                pnl[index] += holding.value * move
    return pnl, (covered / invested if invested else 1.0)


def rule_pnl(rule: GapRule, days: Sequence[date]) -> list[float]:
    """Rupees a day from the rule as it was run: the gap on nights it held, else nothing."""
    return [
        rule.notional * rule.gaps[day] if day in rule.held and day in rule.gaps else 0.0
        for day in days[1:]
    ]
