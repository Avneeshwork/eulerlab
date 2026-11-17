"""Covariance, correlation and component VaR (the parts sum to the whole)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def covariance(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) < 2 or len(a) != len(b):
        return 0.0
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    return sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True)) / (len(a) - 1)


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    """None when either series does not move: a flat book correlates with nothing."""
    var_a, var_b = covariance(a, a), covariance(b, b)
    if var_a <= 0 or var_b <= 0:
        return None
    return covariance(a, b) / math.sqrt(var_a * var_b)


def components(parts: Mapping[str, Sequence[float]], total_var: float) -> dict[str, float]:
    """Each part's rupees of the book's VaR. They sum to `total_var`.

    A part's share is its covariance with the book over the book's variance:
    the Euler split, which is exact for a normal book and the usual
    approximation otherwise. A part that moves against the book has a
    negative share: it is reducing the risk.
    """
    if not parts:
        return {}
    length = len(next(iter(parts.values())))
    book = [sum(series[i] for series in parts.values()) for i in range(length)]
    variance = covariance(book, book)
    if variance <= 0:
        return dict.fromkeys(parts, 0.0)
    return {
        name: round(total_var * covariance(series, book) / variance, 2)
        for name, series in parts.items()
    }
