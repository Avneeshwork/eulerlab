# 011 — Why median absolute deviation, not standard deviation

**Sprint:** 6 · **Date:** 2026-08-19 · **Confidence:** high (properties
derived and measured directly, not taken from a source)

## Question

The build plan assigns "robust statistics: why MAD not stdev" as this sprint's
reading topic. Rather than summarise a textbook, the claims are measured
against this project's own numbers so the operator can check them.

## Finding: a 3-sigma rule is *unable* to fire on a short series

For a sample of `n` points, the largest z-score any single point can have is
bounded:

    max z = (n - 1) / sqrt(n)

| n | max achievable z |
|---|---|
| 5 | 1.79 |
| 10 | 2.85 |
| 11 | 3.02 |
| 30 | 5.29 |
| 250 | 15.75 |

At n=10 no point can reach 3 sigma **no matter how corrupt it is**. A "flag
anything beyond 3 sigma" rule on ten observations is a test that cannot fail.
This is arithmetic and needs no assumption about distributions.

Measured directly: ten returns of about 1% plus one of 60% gives a
standard-deviation z of 2.98 — no flag. The robust score for the same point is
over 30.

## Finding: the standard-deviation score depends on how much clean data surrounds the outlier

The same 60% outlier, with increasing amounts of ordinary data around it:

| n | stdev z | robust z |
|---|---|---|
| 11 | 3.01 | 66.8 |
| 51 | 6.97 | 66.8 |
| 251 | 15.46 | 66.8 |

The robust score is **invariant**. The stdev score varies by a factor of five
for identical corruption, so severity would depend on history length rather
than on the defect. For a quality engine that compares instruments with
different amounts of history, that alone is disqualifying.

## Finding: MAD's own failure mode is degeneracy, not inflation

MAD is exactly zero when more than half the values are identical, and then
every differing point scores infinity. Found by a test: a 19-point series
alternating between +8% and −8% flagged nine rows.

The subtlety is that **imbalance** causes it, not bimodality. A balanced
20-point alternating series has median 0 and MAD 0.08, which is fine. At 19
points one value occurs ten times, the median becomes that value, over half
the deviations are 0, and MAD collapses.

Real cases: an illiquid scrip that closes unchanged most days, or one that
ticks between two values. Handled by returning no spikes and letting the
stale-price check report the flatness once.

## Decision

MAD with a 1.4826 scale factor for relative checks; a separate fixed 30% band
for absolute ones (ADR-017). Degenerate scales return no spikes rather than
flooding.

## What I could not verify

- Whether a different robust estimator (Qn, or an IQR-based scale) would
  handle the degenerate case usefully rather than just deferring it. Not
  needed while the stale-price check covers the same condition.
- The right spike threshold for Indian equities specifically. 5.0 is chosen to
  sit above ordinary market drama, but it is a parameter and has not been
  calibrated against a labelled set of known-bad rows, because no such set
  exists yet.
