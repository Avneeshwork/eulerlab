"""A live deployment judged against its backtest's band."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from eulerlab.risk.book.common import MIN_BAND_DAYS
from eulerlab.risk.book.holdings import Book


def backtest_band(
    backtest: Sequence[float],
    days_live: int,
    quantiles: tuple[float, float, float] = (0.05, 0.5, 0.95),
) -> list[dict[str, float]]:
    """Where the backtest says equity should be after 1..`days_live` days.

    For each horizon, every stretch of that many days in the backtest gives
    one return; the band is the 5th, 50th and 95th percentile of them, with
    the start at 100. Overlapping stretches, so the percentiles are smoother
    than the number of independent periods deserves.
    """
    out: list[dict[str, float]] = [{"day": 0, "low": 100.0, "mid": 100.0, "high": 100.0}]
    for horizon in range(1, days_live + 1):
        moves = sorted(
            backtest[i + horizon] / backtest[i]
            for i in range(len(backtest) - horizon)
            if backtest[i] > 0
        )
        if len(moves) < 20:
            break
        low, mid, high = (moves[min(len(moves) - 1, int(q * len(moves)))] for q in quantiles)
        out.append(
            {
                "day": horizon,
                "low": round(low * 100, 3),
                "mid": round(mid * 100, 3),
                "high": round(high * 100, 3),
            }
        )
    return out


def against_backtest(book: Book, backtest: Sequence[float]) -> dict[str, Any]:
    """The live path beside its backtest band, and a one-word verdict."""
    # The backtest band has no deposits in it, so the live path must not either.
    live = [{"day": 0, "value": 100.0}] + [
        {"day": i, "value": round(value * 100, 3)}
        for i, (_, value) in enumerate(book.growth(), start=1)
    ]
    days_live = len(book.curve)
    band = backtest_band(backtest, days_live) if backtest else []
    verdict, expected = "no_backtest", None
    if band and len(band) > days_live and days_live:
        end, got = band[days_live], live[-1]["value"]
        expected = round(end["mid"] / 100 - 1, 6)
        if days_live < MIN_BAND_DAYS:
            verdict = "too_early"
        else:
            verdict = "below" if got < end["low"] else "above" if got > end["high"] else "inside"
    elif not days_live:
        verdict = "not_started"
    return {"live": live, "band": band, "verdict": verdict, "expected": expected}
