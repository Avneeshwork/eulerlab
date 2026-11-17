"""The most one name may weigh in a book of k names (ADR-120).

Operator, 2026-11-02: "in top 10 no stock can be more than 25%, similarly in 20
stocks no stocks more than 15% weight, in 5 stocks no stocks more than 35%".
Every sizing rule is capped by `max_weight(k)` afterwards (`risk.sizing.size_book`
and `capital_fit`).
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import pairwise

CAPS: tuple[tuple[int, float], ...] = ((1, 1.0), (5, 0.35), (10, 0.25), (20, 0.15))
"""(names held, the most any one may weigh). The 5, 10 and 20 points are the
operator's (ADR-120); 1 name may hold everything. Between points the cap is
interpolated linearly; above 20 names it is 3/k, which is 15% at 20 and keeps
every name within three equal shares (12% of 25, 10% of 30)."""


def max_weight(k: int) -> float:
    """The largest weight any one name may have in a book of `k` names."""
    if k <= 1:
        return 1.0
    last_k, last_cap = CAPS[-1]
    if k >= last_k:
        return 3.0 / k
    for (k0, c0), (k1, c1) in pairwise(CAPS):
        if k0 <= k <= k1:
            return c0 + (c1 - c0) * (k - k0) / (k1 - k0)
    return last_cap  # unreachable: the table covers 1..20


def capped(weights: Mapping[str, float], cap: float) -> dict[str, float]:
    """`weights` rescaled to sum to 1 with no name above `cap`.

    Water-filling: names over the cap are fixed at it, the rest are scaled up
    in proportion to their own weights, and that repeats until nobody is over.
    Needs cap x len(weights) >= 1, which `max_weight` guarantees.
    """
    total = sum(abs(w) for w in weights.values())
    if total <= 0:
        return {}
    fixed: dict[str, float] = {}
    free = {s: abs(w) / total for s, w in weights.items()}
    while True:
        room = 1.0 - cap * len(fixed)
        share = sum(free.values())
        scaled = {s: w * room / share for s, w in free.items()} if share > 0 else {}
        over = [s for s, w in scaled.items() if w > cap * (1 + 1e-12)]
        if not over:
            out = {**dict.fromkeys(fixed, cap), **scaled}
            return {s: out[s] for s in weights}
        for s in over:
            fixed[s] = cap
            del free[s]
