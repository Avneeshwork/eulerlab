# 012 — Calibrating quality thresholds against real data

**Sprint:** 6–7 · **Date:** 2026-08-19 · **Confidence:** high (every number
measured on this project's own data)

## Question

Sprints 6 and 7 shipped with thresholds that were *reasoned* rather than
measured — I said so at the time and left them as open tasks (T-609, T-709).
First contact with real data settled all of them, and three of the four were
wrong in the same way.

## The common mistake: reasoning about scale from the wrong quantity

Each bad threshold came from picking a scale that felt natural and was not the
scale the quantity actually varies on.

| Threshold | First value, and its reasoning | What real data showed | Corrected to |
|---|---|---|---|
| Spike z-score | 5.0 — "Iglewicz & Hoaglin say 3.5, add margin for market drama" | Flagged **1.042%** of 632,133 symbol-days. z=5.1 is merely the **99th percentile of ordinary trading**, because equity returns are fat-tailed | **15.0**, the measured p99.9 |
| Parity slack | ₹1.00 — "options share a ₹0.05 tick, so use ticks not percent" | Flagged **45.95%** of 11,765 traded strike-pairs | **2% of the forward**, ~p99.6 |
| Butterfly slack | ₹0.10 — same tick reasoning | Same failure | **2% of the forward** |
| Monotonicity slack | ₹0.10 — same tick reasoning | Same failure | **1% of the forward** |

The tick argument is genuinely correct for comparing two option *prices* to
each other. It is wrong for a *residual*, which scales with the underlying:
₹50 of error is 0.2% on a 24,000 index and 50% on a ₹100 stock. Getting this
right required noticing that "what tolerance" and "tolerance of what" are
different questions.

## Measured distributions

**Spike z-score**, 632,133 symbol-days:

| threshold | flagged |
|---|---|
| 5 | 1.042% |
| 10 | 0.194% |
| **15** | **0.100%** |
| 20 | 0.045% |

**Parity residual** `|C-P-DF(F-K)|/F`, 11,765 traded pairs: median 0.061%,
p90 0.512%, p99 1.558%. A 2% slack flags 0.40%.

**Butterfly** value/forward, 14,258 equally-spaced triples: median +0.086%,
p5 −0.605%, p1 −2.004%.

**Cross-vendor close difference**, 240 symbol-days of bhavcopy vs Kite minute
bars: median **0.181%**, p90 0.548%, p99 0.906%, max 1.053%. The pre-existing
1% tolerance turned out to sit almost exactly at p99 — the one threshold that
was already right, and it was right because it was reasoned from a mechanism
(NSE computes its close as a 30-minute VWAP, not the last trade) rather than
from a feel for magnitude.

## Finding: butterfly convexity cannot be made quiet, and that is the result

Even at 0.5% of the forward, butterfly still flags 5.73% of triples. This is
not a defect in this pipeline. NSE computes settlement prices for illiquid
strikes with its own model, and those marks are simply not arbitrage-consistent
with one another. The residual ~1% at a 2% slack is a **measurement of the
data source**, and suppressing it further would be hiding a real property.

## Decision

Every threshold is now stated as a measured quantile of a named distribution,
with the sample size, in the constant's own docstring. Where a residual scales
with the underlying, the tolerance is a fraction of the forward rather than an
absolute amount.

This is calibration against a measured distribution, not widening to make
findings disappear. The project rule is unchanged: known defects are
suppressed by name against a STUBS id, never by moving a threshold.

## What I could not verify

- **Whether the surviving findings are truly defects.** There is still no
  labelled set of known-bad rows, so the honest claim remains "rarer than
  99.9% of ordinary observations", not "wrong". Building that labelled set
  from the surviving findings is the next step and would let the thresholds be
  optimised rather than merely calibrated.
- The distributions come from 3 days of F&O and 250 days of cash. Wide enough
  to correct errors of this size; not wide enough to be seasonal.
