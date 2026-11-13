# 191 — Telling decay from bad luck: which sequential test, and what it can do

**Date:** 2026-11-13. **For:** ADR-178, issue #147.

## Question

A strategy trades forward. Each session adds one return. Which test says, as early as it fairly can, that the returns no longer look like the backtest's?

## Sources

| Source | URL | Fetched |
|---|---|---|
| NIST/SEMATECH e-Handbook of Statistical Methods, 6.3.2.3.1 "CUSUM Control Charts" | https://itl.nist.gov/div898/handbook/pmc/section3/pmc3231.htm | 2026-11-13 |

## Findings

- The handbook's standardised CUSUM sums each observation's distance from a reference value `k` and signals when the sum is `h` or more above its lowest earlier point. `k` "might be set equal to" the midpoint between the acceptable mean and the mean to be rejected.
- `h` and `k` are chosen for an average run length: long when nothing has changed, short when the mean has shifted. The handbook says the calculation is "quite involved" and uses tables or a program. Its example: `k = 0.5`, `h = 4` catches a one-standard-deviation shift in about 8 samples.
- "Shewhart is better for detecting large shifts, CUSUM is faster for small shifts." A strategy losing its edge is a small shift: an annual Sharpe of 2 is a daily mean of about 0.13 standard deviations.

## Decision

A one-sided CUSUM on each session's return in backtest units, with `k` at half the fall from the backtest mean to zero. `h` is not taken from a table: it is found per strategy by resampling its own backtest returns in blocks of ten sessions, as the level crossed in no more than the constitution's `false_alarm` share of `horizon_sessions`-long stretches. SPRT was the other candidate; it needs a stopping rule for "accept healthy" that a monitor which never stops watching does not have.

## What it can and cannot do (measured on made-up returns, `tests/test_decay.py`)

For a backtest with daily mean 0.15% and standard deviation 1% (annual Sharpe near 2.4), at a 5% false-alarm rate over 250 sessions:

- the alarm level is about 22;
- a strategy whose mean has gone to zero is caught within 250 sessions about 65% to 70% of the time, with a median near 150 sessions;
- at a 20% false-alarm rate it is caught 87% of the time, median 110 sessions;
- a healthy strategy is on watch (70% of the alarm level) about 3% of sessions.

So a thin edge takes most of a year to be told from noise. A weaker strategy takes longer. The loss limits remain the fast stop; this is the slow one.

## Confidence

Medium. The method is standard. The figures above are from normal, independent made-up returns; real returns cluster, which is why the resampling is in blocks, and nothing has been measured on a real paper book (T-4590).

## What was not found

No source was fetched for the block length; ten sessions is this note's choice (A-139).
