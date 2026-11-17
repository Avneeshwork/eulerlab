"""Equity as an index from 1, with deposits and withdrawals taken out."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

# --- equity paths -------------------------------------------------------------------


def growth(
    curve: Sequence[tuple[date, float]],
    flows: Sequence[tuple[date, float]],
    start: float,
) -> list[tuple[date, float]]:
    """Equity with deposits and withdrawals taken out, as an index from 1.

    Each day's change is measured on the day before's equity plus that day's
    flow, so adding ₹1 L moves the index by nothing and only trading moves it.
    The same rule as `TierBResult.total_return`. Every percentage on the risk
    page is read from this, never from equity against the starting capital:
    that read a deposit as profit (seen 2026-10-17).
    """
    by_day: dict[date, float] = {}
    for day, amount in flows:
        by_day[day] = by_day.get(day, 0.0) + amount
    index, previous = 1.0, start
    out: list[tuple[date, float]] = []
    for day, value in curve:
        base = previous + by_day.get(day, 0.0)
        if base > 0:
            index *= value / base
        out.append((day, index))
        previous = value
    return out
