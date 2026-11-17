"""Beta of the book and of each name to the Nifty (`MARKET`)."""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.risk.book.common import MIN_DAYS
from eulerlab.risk.book.correlation import covariance


def beta(pnl: Sequence[float], equity: float, market: Sequence[float | None]) -> float | None:
    """The book's return per unit of the market's, over days the market traded."""
    pairs = [
        (p / equity, m) for p, m in zip(pnl, market, strict=False) if m is not None and equity > 0
    ]
    if len(pairs) < MIN_DAYS:
        return None
    own, mkt = [p for p, _ in pairs], [m for _, m in pairs]
    variance = covariance(mkt, mkt)
    return covariance(own, mkt) / variance if variance > 0 else None


def name_beta(own: Sequence[float | None], market: Sequence[float | None]) -> float | None:
    """One name's beta to the market, over the days both have a return."""
    pairs = [(o, m) for o, m in zip(own, market, strict=False) if o is not None and m is not None]
    if len(pairs) < MIN_DAYS:
        return None
    mine, mkt = [o for o, _ in pairs], [m for _, m in pairs]
    variance = covariance(mkt, mkt)
    return covariance(mine, mkt) / variance if variance > 0 else None
