"""``min_variance``: long-only minimum variance, each name at most
`max_weight(k)` (Jagannathan & Ma 2003)."""

from __future__ import annotations

import numpy as np

from eulerlab.risk.sizing.common import Matrix


def _project_capped_simplex(v: Matrix, cap: float) -> Matrix:
    """The nearest point to `v` with 0 <= w <= cap and sum(w) = 1."""
    lo, hi = float(v.min()) - cap - 1.0, float(v.max()) + 1.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if float(np.clip(v - mid, 0.0, cap).sum()) > 1.0:
            lo = mid
        else:
            hi = mid
    w: Matrix = np.clip(v - hi, 0.0, cap)
    return w / w.sum()


def min_variance(cov: Matrix, cap: float, iterations: int = 3000) -> Matrix:
    """Long-only minimum variance with every weight at most `cap`, by projected
    gradient descent (no solver dependency; n is at most a few dozen)."""
    n = len(cov)
    cap = max(cap, 1.0 / n)
    scaled = cov / float(np.mean(np.diag(cov)))
    step = 1.0 / (2.0 * float(np.linalg.eigvalsh(scaled).max()))
    w: Matrix = np.full(n, 1.0 / n)
    for _ in range(iterations):
        w = _project_capped_simplex(w - step * 2.0 * scaled @ w, cap)
    return w
