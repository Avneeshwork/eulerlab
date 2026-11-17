"""Risk estimates for the models: daily returns, and a Ledoit-Wolf covariance
shrunk to constant correlation (Ledoit & Wolf 2004)."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from eulerlab.backtest.strategy import MarketView
from eulerlab.risk.sizing.common import MIN_DAYS, WINDOW, Matrix

# --- risk estimates ------------------------------------------------------------------


def returns_matrix(view: MarketView, names: Sequence[str]) -> Matrix | None:
    """Daily close-to-close returns over the last `WINDOW` days, one column per
    name, on the days every name traded. None when that leaves too few days."""
    series: list[dict[Any, float]] = []
    for symbol in names:
        rows = list(view.history.get(symbol) or [])[-(WINDOW + 1) :]
        series.append({b.day: b.close / a.close - 1.0 for a, b in pairwise(rows) if a.close > 0})
    common = set(series[0]).intersection(*series[1:]) if series else set()
    if len(common) < MIN_DAYS:
        return None
    days = sorted(common)
    matrix = np.array([[s[d] for s in series] for d in days], dtype=np.float64)
    if not np.all(np.isfinite(matrix)) or np.any(matrix.std(axis=0) <= 0):
        return None
    return matrix


def ledoit_wolf(returns: Matrix) -> Matrix:
    """Ledoit & Wolf (2004, "Honey, I shrunk the sample covariance matrix"):
    the sample covariance shrunk toward constant correlation by the estimated
    optimal intensity."""
    t, n = returns.shape
    y = returns - returns.mean(axis=0)
    sample = y.T @ y / t
    var = np.diag(sample).copy()
    sd = np.sqrt(var)
    corr = sample / np.outer(sd, sd)
    rbar = float((corr.sum() - n) / (n * (n - 1)))
    target = rbar * np.outer(sd, sd)
    np.fill_diagonal(target, var)
    pi_mat = (y**2).T @ (y**2) / t - sample**2
    # theta[i, j] = E[(y_i^2 - s_ii)(y_i y_j - s_ij)]
    theta = (y**3).T @ y / t - var[:, None] * sample
    ratio = sd[None, :] / sd[:, None]  # ratio[i, j] = sd_j / sd_i
    off = ratio * theta + (ratio * theta).T
    np.fill_diagonal(off, 0.0)
    rho = float(np.trace(pi_mat) + rbar * 0.5 * off.sum())
    gamma = float(((target - sample) ** 2).sum())
    kappa = (float(pi_mat.sum()) - rho) / gamma if gamma > 0 else 0.0
    delta = max(0.0, min(1.0, kappa / t))
    shrunk: Matrix = delta * target + (1.0 - delta) * sample
    return shrunk
