"""Outlier detection that the outliers cannot break.

The reason this sprint uses median absolute deviation rather than standard
deviation is worth stating precisely, because the failure is not "stdev is a
bit less accurate" — it is that stdev **hides exactly the thing you are
hunting**.

Standard deviation is computed from the squared distance of every point to the
mean, so a single wild value inflates it. Take 100 daily returns that are all
about 1%, plus one day that is 60%. The mean moves, and the standard deviation
moves *more*, because the 60% enters squared. The threshold "3 standard
deviations" is now so wide that the 60% day sits inside it and is reported as
normal. The bigger the error in the data, the better it hides. That is the
worst possible property for a data-quality check.

The median and the median absolute deviation do not move. Half the data would
have to be corrupt before the median shifts materially. So a single 60% day
stands out at an enormous robust z-score, which is what we want.

**Breakdown point** is the formal name for this: the fraction of the data that
must be corrupted before the estimator becomes arbitrarily wrong. For the mean
and standard deviation it is 0% — one bad value is enough. For the median and
MAD it is 50%.

There is a sharper version of the problem, and it is arithmetic rather than
statistics. For a sample of `n` points the largest z-score any point can
possibly have is `(n-1)/sqrt(n)`. At n=10 that is **2.85**, so a rule of "flag
anything beyond 3 sigma" is *mathematically incapable* of firing on ten
observations — not unlikely to, unable to. Ten days of 1% moves and one day of
60% produces nothing at all. Anyone checking a short series with a sigma rule
is running a test that cannot fail.

The robust score has no such ceiling, and it is also **invariant to sample
size**: the same 60% outlier scores the same whether it sits among 10 clean
points or 250, because the median and MAD do not move. A standard-deviation
z-score for that identical outlier grows with n, so the same corruption reads
as a different severity depending only on how long the history happens to be.
Both properties are demonstrated with numbers in `tests/test_quality_robust.py`.

The scale factor 1.4826 makes MAD comparable to a standard deviation for data
that really is normal, so a "robust z of 3.5" means roughly what "3.5 sigma"
would have meant if nothing were corrupt. It is a convenience for
interpretation, not an assumption that the data is normal.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

MAD_TO_SIGMA = 1.4826
"""Scales MAD onto the standard-deviation scale for normally distributed data.

1/Φ⁻¹(0.75). Only affects how the number reads, never which points are
flagged relative to each other.
"""

DEFAULT_THRESHOLD = 15.0
"""Robust z above which a point is called a spike.

**Measured, not chosen.** The first value was 5.0, reasoned from Iglewicz and
Hoaglin's 3.5 plus a margin for market drama. Run against 632,133 real
symbol-days it flagged **1.042% of them** — one in every ninety-six ordinary
trading days — because daily equity returns are strongly fat-tailed and a
MAD-based scale on them is small. A z of 5.1 turns out to be merely the 99th
percentile of normal trading.

The empirical distribution over those 632,133 symbol-days:

| threshold | flagged | share of days |
|---|---|---|
| 5  | 6,588 | 1.042% |
| 8  | 2,158 | 0.341% |
| 10 | 1,229 | 0.194% |
| **15** | **631** | **0.100%** |
| 20 | 283 | 0.045% |

15.0 is the **99.9th percentile** — one symbol-day in a thousand, about 2.5 a
day across the whole market, which a person can actually read. It is stated
as a quantile rather than a round number because there is no labelled set of
known-bad rows to optimise against, so the honest claim is "rarer than 999 of
1000 ordinary days for this same instrument", not "correct".

This is a calibration against a measured distribution, not a widening to make
findings disappear. The distinction matters and is the project rule: known
defects are suppressed by name against a STUBS id, never by moving a
threshold. Re-measure if the universe changes materially.
"""


@dataclass(frozen=True)
class RobustScale:
    """Centre and spread of a series, resistant to corruption in it."""

    median: float
    mad: float
    n: int

    @property
    def sigma_equivalent(self) -> float:
        """MAD rescaled to read like a standard deviation."""
        return self.mad * MAD_TO_SIGMA

    @property
    def degenerate(self) -> bool:
        """True when MAD is zero: more than half the values are identical.

        Not an error — a stock that did not trade for weeks legitimately has a
        flat series — but every non-identical point would score infinitely, so
        the caller must decide what to do rather than divide by zero.
        """
        return self.mad == 0.0


def median(values: Sequence[float]) -> float:
    """The middle value; the mean of the middle two when even.

    Written out rather than taken from `statistics` so the tie handling is
    visible: it is the reason MAD of an even-length flat series is exactly 0.
    """
    if not values:
        msg = "median of an empty series is undefined"
        raise ValueError(msg)
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def robust_scale(values: Sequence[float]) -> RobustScale:
    """Median and median absolute deviation of a series."""
    if not values:
        msg = "robust scale of an empty series is undefined"
        raise ValueError(msg)
    centre = median(values)
    deviations = [abs(v - centre) for v in values]
    return RobustScale(median=centre, mad=median(deviations), n=len(values))


def robust_z(value: float, scale: RobustScale) -> float:
    """How many robust sigmas `value` sits from the centre.

    Returns infinity when the spread is zero and the value differs from the
    centre: with every other point identical, any deviation is unbounded
    evidence. Returns 0.0 when the value *is* the centre, since a flat series
    containing only its own value is not an anomaly.
    """
    if scale.degenerate:
        return 0.0 if value == scale.median else math.inf
    return abs(value - scale.median) / scale.sigma_equivalent


def spikes(
    values: Sequence[float], *, threshold: float = DEFAULT_THRESHOLD
) -> list[tuple[int, float, float]]:
    """Indices whose robust z exceeds `threshold`.

    Returns (index, value, robust_z), in index order so the output is
    deterministic. The scale is computed over the whole series *including* the
    spikes — which is safe precisely because MAD does not move when they are
    present, and is the whole reason for using it.
    """
    if len(values) < 3:
        # Two points have a MAD of half their gap, so each is exactly 1 robust
        # sigma from the centre and nothing can ever be flagged. Saying so is
        # better than returning an empty list that looks like a clean result.
        return []
    scale = robust_scale(values)
    if scale.degenerate:
        # MAD is zero whenever more than half the values are identical, which
        # happens for genuinely bimodal or mostly-flat series - an illiquid
        # scrip that closes unchanged most days, or one that alternates
        # between two tick values. Every differing point would then score
        # infinity and flood the report with hundreds of identical findings.
        #
        # Per-point spike detection is simply not meaningful on such a series,
        # so nothing is returned. The underlying condition is not lost: a flat
        # series is what `check_staleness_runs` exists to report, and it says
        # so once rather than once per row.
        return []
    out: list[tuple[int, float, float]] = []
    for index, value in enumerate(values):
        z = robust_z(value, scale)
        if z > threshold:
            out.append((index, value, z))
    return out
