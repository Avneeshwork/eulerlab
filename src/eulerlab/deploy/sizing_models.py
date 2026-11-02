"""How a strategy's money is split across the names it picks (ADR-122).

Operator, 2026-11-02: "use equal sizing with maximum limit as default can be
according to strategy if explicitly defined else from models we develop."

A strategy says *what* to hold, best first. This module says *how much* of
each, by the rule the strategy declares in `Strategy.sizing`:

- ``equal`` (the default) — the strategy's gross exposure split equally over
  its names. A slot strategy holding 4 names at 10% each keeps 10% each: the
  gross is kept, so idle cash stays idle, as the strategy designed.
- ``strategy`` — the strategy's own weights, unchanged. For strategies whose
  weights are part of the idea: Clenow's inverse ATR, betting-against-beta,
  a volatility target, a user's sandbox code.
- ``inverse_vol`` — weight proportional to 1 / sigma over the last 126 days
  (Maillard, Roncalli & Teiletche 2010; Kirby & Ostdiek 2012).
- ``hrp`` — hierarchical risk parity (Lopez de Prado 2016) on a Ledoit-Wolf
  covariance shrunk to constant correlation (Ledoit & Wolf 2004).
- ``min_variance`` — long-only minimum variance on the same covariance, each
  name at most `max_weight(k)` (Jagannathan & Ma 2003).

The caps and the affordability fit (`deploy.sizing`) still apply afterwards:
"maximum limit" is `max_weight(k)` for every rule. The evidence for the
default is research note 140: on five NSE baskets, 2016-2026, no model beat
equal rupees on Sharpe by more than noise.

A model needs history. When fewer than `MIN_DAYS` common return days exist for
the picks (a strategy with a short `lookback`, a new listing), the model falls
back to ``equal`` rather than guess.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Final, Literal, get_args

import numpy as np
import numpy.typing as npt

from eulerlab.deploy.sizing import capped, max_weight

if TYPE_CHECKING:
    from eulerlab.backtest.strategy import MarketView

Sizing = Literal["equal", "strategy", "inverse_vol", "hrp", "min_variance"]
RULES: Final[tuple[str, ...]] = get_args(Sizing)
MODELS: Final[frozenset[str]] = frozenset({"inverse_vol", "hrp", "min_variance"})

WINDOW: Final = 126
"""Trading days of daily returns behind every risk estimate (six months)."""
MIN_DAYS: Final = 60
"""Fewer common return days than this and a model falls back to equal."""
HISTORY_NEEDED: Final = WINDOW + 1
"""Rows a strategy's `lookback` must give a model: `WINDOW` returns need one more close."""

Matrix = npt.NDArray[np.float64]


def rule_of(strategy: Any) -> str:
    """The strategy's declared rule. Unknown values raise: a typo must not
    silently become equal sizing."""
    rule = str(getattr(strategy, "sizing", "equal"))
    if rule not in RULES:
        msg = (
            f"{getattr(strategy, 'name', strategy)!r} declares sizing {rule!r}; use one of {RULES}"
        )
        raise ValueError(msg)
    return rule


def fit_by_order(strategy: Any) -> bool:
    """Whether the capital fit ranks by the strategy's own order. A model's
    weights are sizes, not ranks, so a modelled book always ranks by order."""
    return bool(getattr(strategy, "ranked_by_order", False)) or rule_of(strategy) in MODELS


def size_book(weights: Mapping[str, float], view: MarketView | None, rule: str) -> dict[str, float]:
    """`weights` re-split by `rule`, keeping their order and gross exposure.

    Long weights only (the engines drop shorts first). Zero weights are
    dropped. `view` may be None for ``equal`` and ``strategy``.
    """
    if rule not in RULES:
        msg = f"unknown sizing rule {rule!r}"
        raise ValueError(msg)
    picks = {s: w for s, w in weights.items() if w > 0 and math.isfinite(w)}
    if rule == "strategy" or len(picks) <= 1:
        return picks
    gross = sum(picks.values())
    names = list(picks)
    if rule == "equal":
        return _equal(picks, gross)
    returns = returns_matrix(view, names) if view is not None else None
    if returns is None:
        return _equal(picks, gross)
    if rule == "inverse_vol":
        split = inverse_vol(returns)
    else:
        cov = ledoit_wolf(returns)
        split = hrp(cov) if rule == "hrp" else min_variance(cov, max_weight(len(names)))
    # The cap is applied here as well as in the capital fit, so a model's book
    # obeys it in Tier A too, which does not fit to capital.
    fitted = capped(
        dict(zip(names, (float(w) for w in split), strict=True)), max_weight(len(names))
    )
    return {s: gross * fitted[s] for s in names}


def _equal(picks: dict[str, float], gross: float) -> dict[str, float]:
    values = list(picks.values())
    if max(values) - min(values) <= 1e-12 * max(values):
        # Already equal: returned untouched, so a strategy that sizes equally
        # itself gives byte-identical targets and stored results do not move.
        return picks
    share = gross / len(picks)
    return dict.fromkeys(picks, share)


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


def inverse_vol(returns: Matrix) -> Matrix:
    inv = 1.0 / returns.std(axis=0, ddof=1)
    out: Matrix = inv / inv.sum()
    return out


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


def _single_linkage_order(dist: Matrix) -> list[int]:
    """Leaf order of single-linkage clustering: the quasi-diagonal order of
    HRP's step 2. Ties merge the lowest indices first, so it is deterministic."""
    clusters: list[list[int]] = [[i] for i in range(len(dist))]
    while len(clusters) > 1:
        best: tuple[float, int, int] | None = None
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                d = float(dist[np.ix_(clusters[a], clusters[b])].min())
                if best is None or d < best[0] - 1e-15:
                    best = (d, a, b)
        assert best is not None
        _, a, b = best
        merged = clusters[a] + clusters[b]
        clusters = [c for k, c in enumerate(clusters) if k not in (a, b)] + [merged]
    return clusters[0]


def _cluster_variance(cov: Matrix, members: list[int]) -> float:
    sub = cov[np.ix_(members, members)]
    ivp = 1.0 / np.diag(sub)
    ivp /= ivp.sum()
    return float(ivp @ sub @ ivp)


def hrp(cov: Matrix) -> Matrix:
    """Lopez de Prado (2016): cluster on correlation distance, order the names
    so similar ones sit together, then split weight top-down between halves in
    inverse proportion to each half's variance."""
    sd = np.sqrt(np.diag(cov))
    corr = np.clip(cov / np.outer(sd, sd), -1.0, 1.0)
    dist = np.sqrt(0.5 * (1.0 - corr))
    np.fill_diagonal(dist, 0.0)
    # Distance between the columns of the distance matrix, as in the paper.
    dd = np.sqrt(((dist[:, None, :] - dist[None, :, :]) ** 2).sum(axis=2))
    order = _single_linkage_order(dd)
    weights = np.ones(len(order))
    stack = [order]
    while stack:
        nxt: list[list[int]] = []
        for members in stack:
            if len(members) < 2:
                continue
            left, right = members[: len(members) // 2], members[len(members) // 2 :]
            v_left, v_right = _cluster_variance(cov, left), _cluster_variance(cov, right)
            alpha = 1.0 - v_left / (v_left + v_right)
            weights[left] *= alpha
            weights[right] *= 1.0 - alpha
            nxt += [left, right]
        stack = nxt
    out: Matrix = weights / weights.sum()
    return out


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
