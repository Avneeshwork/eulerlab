# ADR-017 — Outliers are found with MAD, not standard deviation

**Date:** 2026-08-19 · **Sprint:** 6 · **Status:** accepted

**Context.** The quality engine needs to flag prices that look wrong relative
to an instrument's own history. The obvious tool is a z-score: how many
standard deviations from the mean. It does not work, and it fails in the worst
possible direction — the larger the corruption, the better it hides.

**Options.** (a) Standard-deviation z-score with a 3-sigma rule. (b) A fixed
percentage band. (c) Median absolute deviation, scaled to read like sigma.

**Choice.** (c) for relative checks, plus (b) as a separate absolute check.

**Why.** Standard deviation is built from squared distances to the mean, so a
single wild value inflates the threshold that is supposed to catch it. Two
measurements from this sprint's tests make it concrete:

- **A 3-sigma rule cannot fire at all on a short series.** For `n` points the
  largest achievable z-score is `(n-1)/sqrt(n)`. At n=10 that is **2.85** —
  ten days of 1% moves and one day of 60% produces no flag, ever. This is
  arithmetic, not bad luck.
- **A standard-deviation score depends on history length; a robust one does
  not.** The identical 60% outlier scores 3.0 among 11 points and 15.5 among
  251, so the same corruption reads as a different severity depending only on
  how much clean data surrounds it. Its robust score is 66.8 in both cases.

(b) is kept as a *separate* check rather than a replacement, because the two
answer different questions: a fixed 30% band catches an unadjusted corporate
action in any instrument, while MAD catches a 12% move in a utility that has
never moved more than 2%. Neither subsumes the other.

**Cost if wrong.** MAD has one real failure mode, found by a test that
flooded the report: it is exactly zero whenever more than half the values are
identical, which happens for illiquid or bimodal series, and every differing
point then scores infinity. That case is detected and returns no spikes, with
the underlying flatness reported once by the stale-price check instead. If a
future series needs per-point detection despite a degenerate scale, the fix is
a different robust estimator (Qn or IQR), not a return to standard deviation.
