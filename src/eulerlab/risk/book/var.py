"""Value at risk and expected shortfall, three ways: history, normal, recent-weighted (`LAMBDA`)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from eulerlab.risk.book.common import LAMBDA, Z


def quantile_loss(pnl: Sequence[float], confidence: float) -> tuple[float, float]:
    """(VaR, expected shortfall) as positive rupees, by nearest rank.

    VaR is the k-th worst day, k = the days outside the confidence level,
    rounded up and at least one. A book that never lost has a VaR of zero.
    """
    if not pnl:
        return 0.0, 0.0
    ordered = sorted(pnl)
    # Rounded first: (1 - 0.95) * 100 is 5.000000000000004 in floating point,
    # and its ceiling would take a sixth day into a five-day tail.
    k = max(1, math.ceil(round((1 - confidence) * len(ordered), 9)))
    tail = ordered[:k]
    return max(0.0, -tail[-1]), max(0.0, -sum(tail) / len(tail))


def _mean_sd(values: Sequence[float]) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0] if values else 0.0), 0.0
    mean = sum(values) / len(values)
    return mean, math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _normal_tail(mean: float, sd: float, confidence: float) -> tuple[float, float]:
    """VaR and expected shortfall of a normal curve, as positive rupees."""
    z = Z[confidence]
    density = math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
    return max(0.0, z * sd - mean), max(0.0, sd * density / (1 - confidence) - mean)


def recent_sd(pnl: Sequence[float], decay: float = LAMBDA) -> float:
    """Spread with yesterday weighted most: weights fall by `decay` a day back."""
    if not pnl:
        return 0.0
    weight, total, norm = 1.0, 0.0, 0.0
    for value in reversed(pnl):
        total += weight * value * value
        norm += weight
        weight *= decay
    return math.sqrt(total / norm) if norm else 0.0


def var_table(pnl: Sequence[float]) -> list[dict[str, Any]]:
    """The three methods, each at 95% and 99%."""
    mean, sd = _mean_sd(pnl)
    recent = recent_sd(pnl)
    methods: list[tuple[str, str, tuple[float, float], tuple[float, float]]] = [
        (
            "historical",
            f"History, {len(pnl)} days",
            quantile_loss(pnl, 0.95),
            quantile_loss(pnl, 0.99),
        ),
        ("normal", "Normal curve", _normal_tail(mean, sd, 0.95), _normal_tail(mean, sd, 0.99)),
        (
            "recent",
            "Normal curve, recent days weighted",
            _normal_tail(0.0, recent, 0.95),
            _normal_tail(0.0, recent, 0.99),
        ),
    ]
    rows: list[dict[str, Any]] = []
    for key, label, (var95, es95), (var99, es99) in methods:
        rows.append(
            {
                "method": key,
                "label": label,
                "var95": round(var95, 2),
                "var99": round(var99, 2),
                "es95": round(es95, 2),
                "es99": round(es99, 2),
            }
        )
    return rows
