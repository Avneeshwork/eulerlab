# 165 — The good rejected strategies, re-gated under the simple gate

**Question.** Operator, 2026-11-06, after the gate was made simple (ADR-140)
and given a PAPER verdict (ADR-141): "do for good strategies only we found
till now and rejected".

**Choosing "good" without spending trials.** For every strategy the strict
gate had killed, and every intraday rule rejected at screening, the
probabilistic Sharpe was estimated from results already stored (Sharpe and
length, normal returns assumed). Those above the PAPER bar (0.80) were
re-validated and gated; the rest were not:

- Re-gated: the 11 daily strategies the strict gate killed (H-0001, H-0020 to
  H-0029); intraday H-0098 (estimate 1.00), H-0065 (0.84), H-0052 (0.82).
- Not re-gated: H-0078 (0.64), H-0063 (0.62), H-0094 (0.56), H-0073 (0.60),
  H-0053, H-0076 (about 0.5); H-0070 (0.80) because its ten-year version,
  H-0071, was already dead. H-0041 was never rejected and is not here.

Each re-gate is a `make validate` and a `make gate`, two ledger entries
(#68 to #95), run against the worktree's mandate.

## Results

| Hypothesis | What | Net Sharpe (halves) | Years positive | PSR | At 2x costs | Verdict |
|---|---|---|---|---|---|---|
| H-0001 | 12-1 momentum | 1.65 (0.34 / 2.41) | 7 of 9 | 1.000 | 1.61 | **PROMOTE** |
| H-0020 | Risk-adjusted momentum, 1-month skip | 0.98 (0.82 / 1.52) | 6 of 9 | 0.997 | 0.89 | **PROMOTE** |
| H-0021 | Frog in the pan | 1.08 (0.79 / 1.71) | 6 of 9 | 0.999 | 1.04 | **PROMOTE** |
| H-0022 | Risk-adjusted 3-month momentum | 0.87 (0.39 / 1.73) | 6 of 9 | 0.994 | 0.79 | **PROMOTE** |
| H-0029 | Regime-aware factor tilt | 1.29 (0.55 / 2.01) | 6 of 9 | 1.000 | 1.25 | **PROMOTE** |
| H-0098 | F&O ban-day short, daily bars 2015-2024 | 1.90 (1.10 / 2.95) | 9 of 10 | 1.000 | 1.58 | **PROMOTE** |
| H-0023 | 3-month momentum, 1-week delay | 0.91 (0.38 / 1.43) | 5 of 9 | 0.996 | 0.85 | PAPER |
| H-0024 | 3-month momentum, 1-month delay | 0.80 (0.55 / 1.20) | 5 of 9 | 0.990 | 0.74 | PAPER |
| H-0025 | 3-month momentum, 6-month delay | 0.83 | 5 of 9 | 0.992 | | PAPER |
| H-0026 | 6-month momentum, 1-week delay | 1.05 | 5 of 9 | 0.999 | | PAPER |
| H-0027 | Near the 52-week high | 0.88 | 5 of 9 | 0.994 | | PAPER |
| H-0028 | Near the two-year high | 1.05 | 5 of 9 | 0.999 | | PAPER |
| H-0065 | Overnight winners reverse by day (intraday) | 0.55 (1.62 / -0.40) | 2 of 4 | 0.841 | **-3.63** | PAPER |
| H-0052 | NIFTYBEES before a holiday (intraday) | 0.52 (1.03 / -0.42) | 2 of 4 | 0.841 | 0.03 | PAPER |

With H-0096 (PROMOTE earlier), seven strategies are PROMOTE and eight PAPER.
None was killed. The five daily PAPERs all failed only the 60%-of-years rule.

## What the simple gate does not see

- **They are one bet.** Ten of the eleven daily strategies are long-only stock
  momentum or near-high anchoring (H-0029 is a factor tilt). They rise and
  fall together; the strategy map counted 68 India strategies as about three
  independent bets (HISTORY #44).
- **Market and period.** All are long Indian stocks, and 2020-2024 was a
  strong market: second-half Sharpes are two to five times the first. The
  simple gate measures return, not return over the Nifty; the strict gate's
  Romano-Wolf test, which failed them, did.
- **Selection.** H-0001 and H-0029 each have several configurations, and the
  probability that the best one was chosen by luck is 53% and 47%.
- **Search.** None of these clears the deflated Sharpe once the number of
  idea families tried is counted; that is why the strict gate killed them.
- **H-0065 is cost-fragile**: negative at 2x costs (-3.63). It reached PAPER
  because the paper bar does not test costs.
- **H-0098** is the open-auction version of H-0096: it would need orders in
  the 09:00-09:08 pre-open session, which neither the paper engine nor this
  project has built.

PROMOTE and PAPER both allow paper trading; only PROMOTE may later go live,
after paper results. The single holdout read is unspent.
