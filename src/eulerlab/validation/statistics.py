"""Deflated Sharpe, PBO and minimum backtest length.

These three answer one question from three directions: **given how many things
we tried, how impressed should we be?**

A Sharpe ratio computed from a single backtest answers a different and much
easier question — "did this configuration do well on this history" — and the
gap between the two is where most published strategies die. Try a hundred
configurations on the same eleven years and the best one will look excellent
whether or not anything real is there. The maximum of a hundred draws from
pure noise is not a small number.

So every function here takes the **trial count** as a required argument. It is
never defaulted and never inferred, because a defaulted trial count would be
the single most flattering assumption available, and it would be invisible.

References: Bailey and López de Prado on the Deflated Sharpe Ratio and on
minimum backtest length; Bailey, Borwein, López de Prado and Zhu on the
probability of backtest overfitting. The implementations follow those papers;
the value is in using the standard method rather than one I invented.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

EULER_MASCHERONI = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF by bisection.

    Bisection rather than a rational approximation: it is exact to whatever
    tolerance is asked, it cannot silently degrade in the tails where these
    statistics actually live, and it terminates in a fixed number of steps so
    the result is deterministic.
    """
    if not 0.0 < p < 1.0:
        msg = f"probability must be in (0, 1), got {p}"
        raise ValueError(msg)
    low, high = -40.0, 40.0
    for _ in range(200):
        mid = 0.5 * (low + high)
        if _norm_cdf(mid) < p:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


@dataclass(frozen=True)
class SharpeStats:
    sharpe: float
    n: int
    skew: float
    kurtosis: float
    """Excess kurtosis: 0 for a normal distribution."""


def sharpe_stats(returns: Sequence[float], *, periods_per_year: int = 252) -> SharpeStats:
    """Annualised Sharpe plus the moments the deflation needs.

    Skew and kurtosis are not decoration. The Deflated Sharpe correction is
    larger for negatively skewed, fat-tailed return streams — which is exactly
    what most trading strategies produce — so ignoring them understates the
    correction in the flattering direction.
    """
    n = len(returns)
    if n < 3:
        return SharpeStats(0.0, n, 0.0, 0.0)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if variance <= 0:
        return SharpeStats(0.0, n, 0.0, 0.0)
    sd = math.sqrt(variance)

    skew = (sum((r - mean) ** 3 for r in returns) / n) / sd**3
    kurtosis = (sum((r - mean) ** 4 for r in returns) / n) / sd**4 - 3.0
    annualised = (mean / sd) * math.sqrt(periods_per_year)
    return SharpeStats(annualised, n, skew, kurtosis)


def expected_max_sharpe(n_trials: int, *, variance_of_sharpes: float = 1.0) -> float:
    """The Sharpe you would expect from the *best* of `n_trials` worthless strategies.

    This is the benchmark a real strategy has to beat. With enough attempts,
    an impressive-looking Sharpe is the expected outcome of pure noise, and
    this quantifies "enough".
    """
    if n_trials <= 1:
        return 0.0
    sd = math.sqrt(max(variance_of_sharpes, 1e-12))
    n = float(n_trials)
    # Bailey & López de Prado's approximation to the expected maximum of n
    # independent standard normals.
    return sd * (
        (1 - EULER_MASCHERONI) * _norm_ppf(1 - 1 / n)
        + EULER_MASCHERONI * _norm_ppf(1 - 1 / (n * math.e))
    )


def deflated_sharpe(
    stats: SharpeStats,
    *,
    n_trials: int,
    variance_of_sharpes: float = 1.0,
    periods_per_year: int = 252,
) -> float:
    """Probability the true Sharpe is above zero, given how many things were tried.

    Returns a probability, not a ratio. A value of 0.95 means "there is a 95%
    chance this is not noise given `n_trials` attempts"; below about 0.95 the
    result should not be believed however good the raw Sharpe looked.

    `n_trials` is required. Defaulting it to 1 would make every strategy look
    significant and would be the most flattering possible silent assumption.
    """
    if stats.n < 3 or stats.sharpe == 0.0:
        return 0.0

    # Work in per-period units; the moments are per-period too.
    sr = stats.sharpe / math.sqrt(periods_per_year)
    sr0 = expected_max_sharpe(n_trials, variance_of_sharpes=variance_of_sharpes) / math.sqrt(
        periods_per_year
    )

    n = stats.n
    denominator = math.sqrt(max(1e-12, 1.0 - stats.skew * sr + ((stats.kurtosis) / 4.0) * sr**2))
    z = ((sr - sr0) * math.sqrt(n - 1)) / denominator
    return _norm_cdf(z)


def min_backtest_length(n_trials: int, *, target_sharpe: float = 1.0) -> float:
    """Years of history needed before `target_sharpe` is distinguishable from luck.

    The blunt version of the same idea: if the answer exceeds the history you
    actually have, no amount of analysis on that history can support the
    claim. Reported in years because that is the unit the constraint bites in.
    """
    if n_trials <= 1 or target_sharpe <= 0:
        return 0.0
    expected = expected_max_sharpe(n_trials)
    return (expected / target_sharpe) ** 2


@dataclass(frozen=True)
class PBOResult:
    """Probability of backtest overfitting."""

    pbo: float
    n_paths: int
    logits: tuple[float, ...]

    @property
    def verdict(self) -> str:
        if self.n_paths < 4:
            return "too few paths to estimate"
        if self.pbo > 0.5:
            return "worse than a coin flip: the selection is picking noise"
        if self.pbo > 0.25:
            return "substantial overfitting risk"
        return "overfitting risk appears low"


def probability_of_backtest_overfitting(
    in_sample: Sequence[Sequence[float]],
    out_of_sample: Sequence[Sequence[float]],
) -> PBOResult:
    """How often the in-sample winner underperforms out of sample.

    For each split: pick whichever configuration scored best in sample, then
    look up where that same configuration ranks out of sample. If the winner
    lands below the out-of-sample median more often than not, the selection
    procedure is choosing noise — and note that this says nothing about any
    single configuration, it indicts *the act of choosing*.

    `in_sample[i]` and `out_of_sample[i]` are the per-configuration scores for
    split *i*, in the same configuration order.
    """
    if len(in_sample) != len(out_of_sample):
        msg = "in-sample and out-of-sample must cover the same splits"
        raise ValueError(msg)

    logits: list[float] = []
    for is_scores, oos_scores in zip(in_sample, out_of_sample, strict=True):
        if len(is_scores) < 2 or len(is_scores) != len(oos_scores):
            continue
        best = max(range(len(is_scores)), key=lambda i: is_scores[i])
        ranked = sorted(range(len(oos_scores)), key=lambda i: oos_scores[i])
        rank = ranked.index(best) + 1
        # Relative rank in (0, 1); 1.0 would be the top performer.
        omega = rank / (len(oos_scores) + 1)
        logits.append(math.log(omega / (1 - omega)))

    if not logits:
        return PBOResult(0.0, 0, ())

    below = sum(1 for value in logits if value <= 0)
    return PBOResult(below / len(logits), len(logits), tuple(logits))
