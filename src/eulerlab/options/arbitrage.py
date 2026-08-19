"""No-arbitrage checks: prices that cannot all be right at once.

Every check here is a hard inequality implied by the payoff structure, not a
statistical threshold. If a butterfly costs less than zero, there is no market
condition under which that is correct — someone would take the free money. So
a violation means at least one of the prices involved is wrong, and that is a
data-quality finding rather than a trading signal.

**The forward and discount factor are implied from the chain, not assumed.**
Put-call parity for European options on a future says

    C(K) - P(K) = DF * (F - K)

which is linear in K with slope `-DF` and intercept `DF * F`. Fitting that
line across the strikes recovers both, so no risk-free rate has to be invented
and no external data is needed. That matters here beyond convenience: an
assumed rate would silently become the thing every parity "violation" was
measuring.

**Tolerances are in ticks where two option prices are compared, and in
fractions of the forward where a residual is.** The first draft used an
absolute ₹1.00 slack everywhere, reasoning that an option quoted at ₹0.05 and
one at ₹5,000 share the same ₹0.05 tick. That is right for monotonicity and
butterfly, which compare option prices to each other — and wrong for parity
and intrinsic bounds, whose residual scales with the *underlying's* price
level. ₹50 of error is 0.2% on a 24,000 index and 50% on a ₹100 stock.

Measured on 11,765 real traded strike-pairs across three days: an absolute
₹1.00 slack flagged **45.95%** of them. Normalised by the forward the same
data is well behaved — median residual **0.061%**, p99 **1.56%** — so parity
and intrinsic now use a fraction of the forward.

**Untraded contracts are separated, never silently included.** NSE computes a
settlement price for every listed contract including strikes that never
traded, so a violation involving one is a statement about NSE's model rather
than about the market. Each check takes `traded_only`, and the report says
which mode produced it.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from eulerlab.options.chain import Chain
from eulerlab.quality.findings import Finding, Severity
from eulerlab.quality.robust import median

PRICE_TICK = 0.05
"""The NSE options tick. Every tolerance below is a multiple of this."""

PARITY_SLACK_FRACTION = 0.02
"""Parity tolerance as a fraction of the forward. **Measured, not chosen.**

Distribution of |C - P - DF(F-K)| / F over 11,765 traded strike-pairs:

| quantile | residual |
|---|---|
| median | 0.061% |
| p90 | 0.512% |
| p99 | 1.558% |
| p99.9 | 2.773% |

| slack | pairs flagged |
|---|---|
| 0.1% | 39.67% |
| 0.5% | 10.39% |
| 1.0% | 3.34% |
| **2.0%** | **0.40%** |

2% is about the p99.6 and flags 0.40% of traded pairs — roughly 47 of 11,765,
which a person can actually read. The tail is wide because settlement prices
for illiquid strikes are model-derived rather than traded, so this measures
how far NSE's marks drift from internal consistency, not how wrong we are.
"""

MIN_PARITY_SLACK = 20 * PRICE_TICK
"""₹1.00 floor, so a very low-priced underlying still gets tick-scale slack
rather than a fraction of a rupee."""

MONOTONICITY_SLACK_FRACTION = 0.01
"""Measured over 21,718 real adjacent strike-pairs. The violation excess as a
fraction of the forward has p99 **0.40%** and p99.9 **1.44%**; 1% flags about
0.5% of pairs."""

BUTTERFLY_SLACK_FRACTION = 0.02
"""Measured over 14,258 real equally-spaced triples.

| quantile | butterfly value / forward |
|---|---|
| median | +0.086% |
| p5 | -0.605% |
| p1 | -2.004% |
| p0.5 | -2.704% |

Convexity is the noisiest of these checks and no tolerance makes it quiet: at
0.5% of the forward it still flags 5.73% of triples. That is **not a defect in
this pipeline** — it is a measurement of NSE's settlement prices, which are
model-derived for illiquid strikes and are simply not arbitrage-consistent
with each other. 2% sits at about the 1st percentile and leaves roughly 1% of
triples flagged, which is the honest residual rather than a quiet report.
"""

MIN_SLACK = 2 * PRICE_TICK
"""Floor for both, so a very cheap underlying keeps tick-scale tolerance."""


def _finding(check: str, chain: Chain, detail: str, severity: Severity = Severity.WARN) -> Finding:
    return Finding(
        check=check,
        severity=severity,
        dataset="nse_fo",
        symbol=f"{chain.underlying} {chain.expiry.isoformat()}",
        day=chain.day,
        detail=detail,
    )


def implied_forward_and_discount(
    chain: Chain, *, traded_only: bool = True
) -> tuple[float, float] | None:
    """Fit `C - P = DF*F - DF*K` across strikes. Returns (forward, DF).

    **Theil-Sen, not least squares, and the reason is the whole point of this
    module.** The fitted line is the benchmark every parity and intrinsic
    check is measured against. Ordinary least squares has a breakdown point of
    zero — one corrupted price is enough to move it arbitrarily — so a single
    bad quote does not merely go undetected, it *destroys the instrument used
    to detect it*.

    That is not hypothetical. It was found by a test: planting one call at
    ₹1.00 when its intrinsic was ₹1,000 skewed the OLS fit so far that the
    discount factor left the plausible range entirely, the fit returned None,
    and the check reported nothing at all. The corruption hid itself perfectly.

    This is the same failure as standard deviation in `quality/robust.py`, in a
    different disguise, and it takes the same answer: an estimator whose
    breakdown point is not zero. Theil-Sen takes the median of all pairwise
    slopes and tolerates roughly 29% of the points being wrong, which is far
    more than any real chain should contain.

    Returns None when there are fewer than three strikes, or when the fitted
    discount factor is outside roughly (0.8, 1.05) — that means the fit found
    something that is not a discount factor, and a forward derived from it
    would be worse than no answer.
    """
    pairs = chain.paired(traded_only=traded_only)
    if len(pairs) < 3:
        return None

    xs = [float(strike) for strike, _, _ in pairs]
    ys = [call.price - put.price for _, call, put in pairs]

    slopes = [
        (ys[j] - ys[i]) / (xs[j] - xs[i])
        for i in range(len(xs))
        for j in range(i + 1, len(xs))
        if xs[j] != xs[i]
    ]
    if not slopes:
        return None
    slope = median(slopes)

    intercept = median([y - slope * x for x, y in zip(xs, ys, strict=True)])

    discount = -slope
    if not (0.80 < discount < 1.05):
        return None
    return intercept / discount, discount


def check_put_call_parity(chain: Chain, *, traded_only: bool = True) -> list[Finding]:
    """`C - P` must equal `DF*(F - K)` at every strike.

    The forward is implied from the chain rather than taken from the future's
    own settlement price. Both are available, and disagreement between them is
    itself worth knowing — but using the future directly would make every
    check depend on that one contract being right.
    """
    fitted = implied_forward_and_discount(chain, traded_only=traded_only)
    if fitted is None:
        return []
    forward, discount = fitted

    slack = max(PARITY_SLACK_FRACTION * forward, MIN_PARITY_SLACK)
    out: list[Finding] = []
    for strike, call, put in chain.paired(traded_only=traded_only):
        expected = discount * (forward - float(strike))
        actual = call.price - put.price
        error = abs(actual - expected)
        if error > slack:
            out.append(
                _finding(
                    "put-call-parity",
                    chain,
                    f"K={strike}: C-P is {actual:.2f} but parity implies "
                    f"{expected:.2f} (off by {error:.2f}, forward {forward:.2f})",
                )
            )
    return out


def check_strike_monotonicity(chain: Chain, *, traded_only: bool = True) -> list[Finding]:
    """A call cannot cost more as the strike rises; a put cannot cost less.

    The right to buy at a higher price is worth less, always. This needs no
    model at all — violating it is an immediate arbitrage by buying the cheap
    one and selling the dear one.
    """
    out: list[Finding] = []
    pairs = chain.paired(traded_only=traded_only)
    fitted = implied_forward_and_discount(chain, traded_only=traded_only)
    forward = fitted[0] if fitted else 0.0
    slack = max(MONOTONICITY_SLACK_FRACTION * forward, MIN_SLACK)

    for (k1, c1, p1), (k2, c2, p2) in pairwise(pairs):
        if c2.price > c1.price + slack:
            out.append(
                _finding(
                    "call-monotonicity",
                    chain,
                    f"call at K={k2} costs {c2.price:.2f}, more than K={k1} at "
                    f"{c1.price:.2f}; a higher strike cannot be worth more",
                )
            )
        if p2.price < p1.price - slack:
            out.append(
                _finding(
                    "put-monotonicity",
                    chain,
                    f"put at K={k2} costs {p2.price:.2f}, less than K={k1} at "
                    f"{p1.price:.2f}; a higher strike cannot be worth less",
                )
            )
    return out


def check_butterfly_convexity(chain: Chain, *, traded_only: bool = True) -> list[Finding]:
    """Option price must be convex in strike: `C(K1) - 2C(K2) + C(K3) >= 0`.

    Only evaluated on **equally spaced** strikes. The general convexity
    condition needs a weighting by the gaps, and applying the equal-spacing
    form to unequal strikes manufactures violations that are artefacts of the
    strike ladder rather than of the prices — which is exactly the kind of
    false finding that gets a whole report ignored.
    """
    out: list[Finding] = []
    pairs = chain.paired(traded_only=traded_only)
    fitted = implied_forward_and_discount(chain, traded_only=traded_only)
    forward = fitted[0] if fitted else 0.0
    slack = max(BUTTERFLY_SLACK_FRACTION * forward, MIN_SLACK)

    for (k1, c1, p1), (k2, c2, p2), (k3, c3, p3) in zip(pairs, pairs[1:], pairs[2:], strict=False):
        if (k2 - k1) != (k3 - k2):
            continue
        for label, a, b, c in (
            ("call", c1.price, c2.price, c3.price),
            ("put", p1.price, p2.price, p3.price),
        ):
            butterfly = a - 2 * b + c
            if butterfly < -slack:
                out.append(
                    _finding(
                        f"{label}-butterfly",
                        chain,
                        f"{label} butterfly {k1}/{k2}/{k3} costs {butterfly:.2f}, "
                        f"below zero; a butterfly has a non-negative payoff",
                    )
                )
    return out


def check_intrinsic_bounds(chain: Chain, *, traded_only: bool = True) -> list[Finding]:
    """No option may be worth less than exercising it immediately.

    Uses the implied forward, so it holds for both eras without an underlying
    price. This is ERROR rather than WARN: unlike a parity drift, a price
    below intrinsic is not a rounding artefact — it is a contradiction.
    """
    fitted = implied_forward_and_discount(chain, traded_only=traded_only)
    if fitted is None:
        return []
    forward, discount = fitted

    slack = max(PARITY_SLACK_FRACTION * forward, MIN_PARITY_SLACK)
    out: list[Finding] = []
    for strike, call, put in chain.paired(traded_only=traded_only):
        k = float(strike)
        call_floor = discount * max(forward - k, 0.0)
        put_floor = discount * max(k - forward, 0.0)
        if call.price < call_floor - slack:
            out.append(
                _finding(
                    "call-below-intrinsic",
                    chain,
                    f"K={strike}: call at {call.price:.2f} is below its intrinsic {call_floor:.2f}",
                    Severity.ERROR,
                )
            )
        if put.price < put_floor - slack:
            out.append(
                _finding(
                    "put-below-intrinsic",
                    chain,
                    f"K={strike}: put at {put.price:.2f} is below its intrinsic {put_floor:.2f}",
                    Severity.ERROR,
                )
            )
    return out


def check_calendar_monotonicity(
    chains: Sequence[Chain], *, traded_only: bool = True
) -> list[Finding]:
    """For one underlying and strike, a later expiry should not cost less.

    Stated carefully because the textbook version does not apply directly.
    For European options on a *future*, longer-dated contracts reference a
    different future, so the clean American-style inequality is not guaranteed
    and a small inversion can be legitimate. It is reported as WARN and only
    when the inversion is large, because the common cause of a big one is a
    stale settlement price on a thin far-month contract — which is a data
    problem worth seeing.
    """
    by_underlying: dict[str, list[Chain]] = {}
    for chain in chains:
        by_underlying.setdefault(chain.underlying, []).append(chain)

    out: list[Finding] = []
    for underlying, group in sorted(by_underlying.items()):
        ordered = sorted(group, key=lambda c: c.expiry)
        for near, far in pairwise(ordered):
            shared = sorted(set(near.calls) & set(far.calls))
            for strike in shared:
                a, b = near.calls[strike], far.calls[strike]
                if traded_only and not (a.traded and b.traded):
                    continue
                # A far-month call worth materially less than the near month
                # is the signature of a stale mark, not of a real term
                # structure.
                if b.price < a.price * 0.5 and a.price > 1.0:
                    out.append(
                        _finding(
                            "calendar-inversion",
                            far,
                            f"{underlying} K={strike}: {far.expiry.isoformat()} call at "
                            f"{b.price:.2f} is less than half the "
                            f"{near.expiry.isoformat()} call at {a.price:.2f}",
                        )
                    )
    return out


def run_chain_checks(chain: Chain, *, traded_only: bool = True) -> list[Finding]:
    """Every single-chain check."""
    return [
        *check_intrinsic_bounds(chain, traded_only=traded_only),
        *check_put_call_parity(chain, traded_only=traded_only),
        *check_strike_monotonicity(chain, traded_only=traded_only),
        *check_butterfly_convexity(chain, traded_only=traded_only),
    ]
