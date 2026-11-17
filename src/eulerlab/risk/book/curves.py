"""Combined curves, drawdowns, today's profit and the profit-and-loss histogram."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from eulerlab.risk.book.holdings import Book


def histogram(pnl: Sequence[float], equity: float, bins: int = 12) -> list[dict[str, float]]:
    """Daily results as % of equity, counted into equal bins centred on zero."""
    if not pnl or equity <= 0:
        return []
    moves = [p / equity * 100 for p in pnl]
    # The range covers the 1st to 99th percentile; the few days beyond are
    # counted into the end bins. One freak day would otherwise set the scale
    # and leave every ordinary day in two bars.
    ordered = sorted(moves)
    edge = max(0, round(0.01 * len(ordered)) - 1) if len(ordered) >= 100 else 0
    reach = max(abs(ordered[edge]), abs(ordered[-1 - edge]), 1e-9)
    # A round edge, so the axis reads 2.5% rather than 2.3718%.
    step = next(
        s for s in (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 100.0) if s * bins / 2 >= reach
    )
    low = -step * bins / 2
    counts = [0] * bins
    for move in moves:
        counts[min(bins - 1, max(0, int((move - low) / step)))] += 1
    return [
        {"from": round(low + i * step, 4), "to": round(low + (i + 1) * step, 4), "days": count}
        for i, count in enumerate(counts)
    ]


def drawdown(curve: Sequence[tuple[date, float]]) -> dict[str, Any]:
    """Where a path sits below its highest point so far, and the deepest it has been.

    Pass `growth(...)`, not equity: a withdrawal is not a drawdown.
    """
    peak = 0.0
    peak_day: date | None = None
    deepest, deepest_day = 0.0, None
    path: list[tuple[str, float]] = []
    now = 0.0
    for day, value in curve:
        if value > peak:
            peak, peak_day = value, day
        now = value / peak - 1 if peak > 0 else 0.0
        if now < deepest:
            deepest, deepest_day = now, day
        path.append((day.isoformat(), round(now, 6)))
    return {
        "now": round(now, 6),
        "deepest": round(deepest, 6),
        "deepest_day": deepest_day.isoformat() if deepest_day else None,
        "peak_day": peak_day.isoformat() if peak_day else None,
        "path": path,
    }


def combined_curve(books: Sequence[Book]) -> list[tuple[date, float]]:
    """The whole book's equity by day.

    A deployment counts at its capital before its first day and at its last
    known equity after its latest, so the sum is always all the money.
    """
    days = sorted({day for book in books for day, _ in book.curve})
    out: list[tuple[date, float]] = []
    last = {book.id: book.capital for book in books}
    by_day = [dict(book.curve) for book in books]
    for day in days:
        for book, curve in zip(books, by_day, strict=True):
            if day in curve:
                last[book.id] = curve[day]
        out.append((day, round(sum(last.values()), 2)))
    return out


def today_pnl(book: Book, as_of: date | None) -> float:
    """The last day's change in equity, less any money moved in that day."""
    if len(book.curve) < 2 or (as_of is not None and book.curve[-1][0] != as_of):
        return 0.0
    last = book.curve[-1][0]
    moved = sum(amount for day, amount in book.flows if day == last)
    return book.curve[-1][1] - book.curve[-2][1] - moved
