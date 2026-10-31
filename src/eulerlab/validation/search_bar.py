"""The Sharpe bar from what was searched, not from how many rows the ledger has (ADR-108).

Research 138. The deflated Sharpe (ARCHITECTURE 5.3) compares a strategy with
the best of N worthless ones. Until 2026-10-31, N was the number of ledger
rows and the spread of Sharpes was assumed to be 1.0 (A-021), so a tenth
variant of one idea raised the bar as much as a new idea, and the assumed
spread was about twice the measured one. The operator chose to replace that
with two checks, both of which still correct for the search:

1. **Families (López de Prado and Lewis 2019).** Every strategy ever tested is
   clustered by return correlation; N is the number of families and sigma_SR is
   the measured spread of the families' annualised Sharpes. The deflated
   Sharpe is computed against that bar.
2. **Romano-Wolf StepM (2005).** The candidate's daily return over Nifty is
   tested jointly with every other strategy's, by a stationary block
   bootstrap of all of them together. The critical value comes from the
   bootstrap distribution of the maximum statistic, so correlation between
   strategies is accounted for and no N or sigma is assumed. The candidate passes
   only if StepM rejects "no edge over Nifty" for it at the mandate's level.

"Everything tested" is every stored India equity report (one configuration per
strategy, `research/strategy_map.collect`) plus the candidate hypothesis's own
configurations. Sweeps that store no daily returns are invisible to both
checks (T-4301); that is the main way this bar can be too low.

Families are formed with equal weight inside a family, not the paper's
minimum-variance weights, and by average-linkage clustering, not ONC (S-057).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from eulerlab.research import strategy_map
from eulerlab.validation.statistics import expected_max_sharpe

SEED = 20261031
"""Fixed so the same returns give the same verdict (determinism rule)."""

TRADING_DAYS = 252.0
MIN_COVERAGE = 0.9
"""A strategy joins the Romano-Wolf set only if it traded on at least this
share of the candidate's days; the test needs one common window."""


@dataclass(frozen=True)
class FamilyBar:
    strategies: int
    families: int
    sigma: float
    bar: float


@dataclass(frozen=True)
class RomanoWolf:
    passed: bool
    alpha: float
    candidate_sharpe: float
    critical_sharpe: float
    strategies: int
    days: int
    first_day: str
    last_day: str
    block_days: int
    draws: int


def family_bar(universe: Sequence[Mapping[date, float]], *, join_at: float) -> FamilyBar | None:
    """N = families at `join_at`, sigma = spread of family Sharpes, bar = expected max."""
    series = [dict(s) for s in universe if len(s) >= 2]
    if len(series) < 2:
        return None
    groups = strategy_map.families(strategy_map.matrix(series), join_at=join_at)
    sharpes = []
    for group in groups:
        blended = strategy_map.book([series[i] for i in group], [list(range(len(group)))])
        value = strategy_map.sharpe(list(blended.values()))
        if value is not None:
            sharpes.append(value)
    if len(sharpes) < 2:
        return None
    sigma = float(np.std(sharpes, ddof=1))
    bar = expected_max_sharpe(len(groups), variance_of_sharpes=sigma * sigma)
    return FamilyBar(len(series), len(groups), round(sigma, 4), round(bar, 4))


def _stationary_indices(rng: np.random.Generator, length: int, block: int) -> np.ndarray:
    """Politis-Romano stationary bootstrap: blocks of geometric length, mean `block`."""
    jumps = rng.random(length) < 1.0 / block
    jumps[0] = True
    starts = rng.integers(length, size=length)
    group = np.cumsum(jumps) - 1
    first = np.flatnonzero(jumps)
    offset = np.arange(length) - first[group]
    return (starts[first][group] + offset) % length


def romano_wolf(
    candidate: Mapping[date, float],
    others: Sequence[Mapping[date, float]],
    market: Mapping[date, float],
    *,
    alpha: float,
    block_days: int,
    draws: int,
    seed: int = SEED,
) -> RomanoWolf | None:
    """StepM on daily returns over the market; does it reject for the candidate?

    Statistic: the studentised mean, sqrt(T) * mean / sd. Index 0 is the
    candidate. Steps down until no further strategy is rejected.
    """
    days = [d for d in sorted(candidate) if d in market]
    if len(days) < 2 * block_days:
        return None
    wanted = set(days)
    members = [o for o in others if len(wanted & o.keys()) >= MIN_COVERAGE * len(days)]
    for member in members:
        wanted &= member.keys()
    common = sorted(wanted)
    if len(common) < 2 * block_days:
        return None
    columns = [candidate, *members]
    excess = np.array([[c[d] - market[d] for c in columns] for d in common], dtype=float)
    length = len(common)
    mean = excess.mean(0)
    sd = excess.std(0, ddof=1)
    sd[sd == 0] = np.inf
    stat = math.sqrt(length) * mean / sd

    rng = np.random.default_rng(seed)
    boots = np.empty((draws, excess.shape[1]))
    for b in range(draws):
        sample = excess[_stationary_indices(rng, length, block_days)]
        s_sd = sample.std(0, ddof=1)
        s_sd[s_sd == 0] = np.inf
        boots[b] = math.sqrt(length) * (sample.mean(0) - mean) / s_sd

    rejected = np.zeros(len(stat), dtype=bool)
    critical = float("inf")
    while not rejected.all():
        remaining = ~rejected
        critical = float(np.quantile(boots[:, remaining].max(1), 1 - alpha))
        newly = remaining & (stat > critical)
        if not newly.any():
            break
        rejected |= newly
    scale = math.sqrt(TRADING_DAYS / length)
    return RomanoWolf(
        passed=bool(rejected[0]),
        alpha=alpha,
        candidate_sharpe=round(float(stat[0]) * scale, 4),
        critical_sharpe=round(critical * scale, 4) if math.isfinite(critical) else critical,
        strategies=len(columns),
        days=length,
        first_day=common[0].isoformat(),
        last_day=common[-1].isoformat(),
        block_days=block_days,
        draws=draws,
    )


def stored_universe(root: Path = strategy_map.WORKSPACES) -> list[dict[date, float]]:
    """Every stored India equity strategy's daily returns, one configuration each."""
    return [s.returns for s in strategy_map.collect(root)]


def assess(
    candidate: Mapping[date, float],
    siblings: Sequence[Mapping[date, float]],
    rules: Mapping[str, Any],
    *,
    universe: Sequence[Mapping[date, float]] | None = None,
    market: Mapping[date, float] | None = None,
) -> dict[str, Any]:
    """The evidence pack's `search` block. Missing pieces stay missing; the gate fails them."""
    stored = stored_universe() if universe is None else list(universe)
    everything = [*stored, dict(candidate), *siblings]
    out: dict[str, Any] = {"method": None, "strategies_seen": len(everything)}
    bar = family_bar(everything, join_at=float(rules["family_join_correlation"]))
    if bar is not None:
        out["method"] = "families"
        out["families"] = asdict(bar)
    nifty = strategy_map.nifty_returns() if market is None else market
    if nifty:
        test = romano_wolf(
            candidate,
            [*stored, *siblings],
            nifty,
            alpha=float(rules["romano_wolf_alpha"]),
            block_days=int(rules["romano_wolf_block_days"]),
            draws=int(rules["romano_wolf_draws"]),
        )
        if test is not None:
            out["romano_wolf"] = asdict(test)
    return out
