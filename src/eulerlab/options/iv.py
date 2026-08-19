"""Implied volatility, computed here rather than taken from a vendor.

Two reasons the build plan wants our own number. A vendor's IV is computed
with a model and inputs we cannot see, so a disagreement with it is
uninterpretable. And an IV that fails to solve is itself a data-quality
finding — it means the price is outside the range any volatility could
produce, which is exactly what this sprint is looking for.

**Black-76, not Black-Scholes.** Indian index options are European and
cash-settled against the index, and the natural hedge instrument is the
same-expiry future, which is quoted in the same file. Black-76 prices an
option directly off the forward:

    call = DF * (F*N(d1) - K*N(d2))
    put  = DF * (K*N(-d2) - F*N(-d1))
    d1 = (ln(F/K) + sigma^2*T/2) / (sigma*sqrt(T)),  d2 = d1 - sigma*sqrt(T)

Using spot-based Black-Scholes would require a dividend assumption for stock
options and a repo assumption for the index, neither of which we have. The
forward already contains both.

**Bisection, not Newton.** Newton is faster but can diverge for deep
out-of-the-money options where vega is nearly zero, and a solver that
sometimes fails to terminate is unacceptable in a batch that runs over
millions of contracts. Bisection on a bounded bracket always terminates in a
fixed number of steps, and the fixed count also makes the result
deterministic — a project-wide rule.
"""

from __future__ import annotations

import math

from eulerlab.master.derivatives import Right

MIN_VOL = 1e-4
MAX_VOL = 5.0
"""500% annualised. Above this the price is essentially all time value and the
number stops being meaningful, so the solver reports failure instead."""

BISECTION_STEPS = 100
"""Fixed, so runtime and result are both deterministic. 100 halvings of the
(0, 5] bracket resolves far finer than any price tick justifies."""


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function.

    `math.erf` is in the standard library and accurate to machine precision,
    so there is no reason to carry an approximation or a dependency.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black76_price(
    *, forward: float, strike: float, years: float, vol: float, discount: float, right: Right
) -> float:
    """Price a European option on a forward."""
    if years <= 0 or vol <= 0 or forward <= 0 or strike <= 0:
        intrinsic = (
            max(forward - strike, 0.0) if right is Right.CALL else max(strike - forward, 0.0)
        )
        return discount * intrinsic

    sqrt_t = math.sqrt(years)
    d1 = (math.log(forward / strike) + 0.5 * vol * vol * years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    if right is Right.CALL:
        return discount * (forward * _norm_cdf(d1) - strike * _norm_cdf(d2))
    return discount * (strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1))


def implied_vol(
    *,
    price: float,
    forward: float,
    strike: float,
    years: float,
    discount: float,
    right: Right,
) -> float | None:
    """Invert Black-76 for volatility. None when no volatility fits.

    Returning None rather than a number is the point. A price below intrinsic
    or above the theoretical maximum cannot be produced by *any* volatility,
    so there is no answer to give — and a solver that clamps to a boundary
    instead would hide precisely the mispriced contracts this sprint exists to
    find.
    """
    if price <= 0 or years <= 0 or forward <= 0 or strike <= 0:
        return None

    intrinsic = discount * (
        max(forward - strike, 0.0) if right is Right.CALL else max(strike - forward, 0.0)
    )
    if price < intrinsic - 1e-9:
        return None  # below intrinsic: no volatility can produce this

    def priced(vol: float) -> float:
        return black76_price(
            forward=forward,
            strike=strike,
            years=years,
            vol=vol,
            discount=discount,
            right=right,
        )

    if price > priced(MAX_VOL):
        return None  # above what 500% vol produces

    low, high = MIN_VOL, MAX_VOL
    for _ in range(BISECTION_STEPS):
        mid = 0.5 * (low + high)
        if priced(mid) < price:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def years_to_expiry(days: int, *, days_per_year: float = 365.0) -> float:
    """Calendar-day year fraction.

    Calendar days rather than trading days, deliberately. Option time value
    decays over calendar time — a weekend costs theta — and the two
    conventions differ by about 30%, which would show up as a systematic bias
    in every IV. Recorded here rather than left implicit because it is the
    single most common silent disagreement between two IV calculations.
    """
    return max(days, 0) / days_per_year
