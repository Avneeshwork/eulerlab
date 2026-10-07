# 067 — Tuning volatility-adjusted momentum, and whether the tuning is real

**Question.** Operator: "optimize this strategy and ensure no overfitting —
Volatility-adjusted momentum, top 30 (India)", then "optimize the set of
parameters in the strategy, no other parameter addition". Which of the
strategy's own settings should it run with, and does any setting beat the
paper's once overfitting is accounted for?

No web sources: this is a measurement on the panel. Run 2026-10-07 with
`make tune-sharpe-momentum` (`src/eulerlab/research/tune_sharpe_momentum.py`).

## What was swept

The strategy's three settings and nothing else. 4 × 4 × 4 = 64 settings.

| Setting | Values | Paper |
|---|---|---|
| Window the return and volatility are measured over | 63, 126, 189, 252 sessions | 252 |
| Names held, equal-weighted | 10, 20, 30, 50 | 30 |
| Sessions between rebalances | 10, 21, 42, 63 | 21 |

Each setting ran once over the whole panel, Tier B, Indian costs, ₹10 lakh,
point-in-time top 250, warm-up 253 sessions (trading from 2016-01). The paper
setting reproduced research 064 exactly: Sharpe 1.035, +814%, 4,601 fills.

**In-sample:** 2016-01 to 2023-12. **Holdout:** 2024-01-01 to 2026-09-30.
Every choice was made on in-sample only. Research 064 had already run the
paper setting through the holdout years, so the holdout is unseen by the
*choice*, not by the project.

**Choosing:** the setting with the best mean in-sample Sharpe across itself and
its one-step grid neighbours (a plateau, not a peak).

## Results, after costs

| | Setting | In-sample Sharpe | CAGR | Max DD | Holdout Sharpe | CAGR | Max DD | Fills | Costs |
|---|---|---|---|---|---|---|---|---|---|
| Chosen (best plateau) | 252 / 10 / 10 | 1.26 | 35.1% | -39% | 1.16 | 33.3% | -38% | 3,199 | ₹10.2 lakh |
| Paper | 252 / 30 / 21 | 1.12 | 25.5% | -44% | 0.80 | 17.8% | -30% | 4,601 | ₹3.4 lakh |
| Best single point | 252 / 20 / 10 | 1.32 | 33.3% | -34% | 0.82 | 19.8% | -38% | 6,063 | — |

At **2× costs**: chosen 1.20 in-sample / 1.11 holdout; paper 1.08 / 0.76.

Average Sharpe by one setting, across the other two:

| Window | 63 | 126 | 189 | 252 |
|---|---|---|---|---|
| In-sample | 0.98 | 1.08 | 1.16 | 1.15 |
| Holdout | 0.58 | 0.57 | 0.80 | 0.78 |

| Names held | 10 | 20 | 30 | 50 |
|---|---|---|---|---|
| In-sample | 1.12 | 1.11 | 1.08 | 1.05 |
| Holdout | 0.65 | 0.69 | 0.69 | 0.69 |

| Rebalance | 10 | 21 | 42 | 63 |
|---|---|---|---|---|
| In-sample | 1.11 | 1.06 | 1.07 | 1.12 |
| Holdout | 0.73 | 0.62 | 0.68 | 0.69 |

## Overfitting checks

| Check | Result | Reading |
|---|---|---|
| Walk-forward, 2019-2023 (re-choose each year on the years before) | Sharpe 1.28, +307% | Keeping the paper setting earned **1.38, +305%** over the same years. Re-tuning added nothing |
| PBO, CSCV over 8 in-sample blocks, 70 splits | **0.71** | The in-sample winner lands below the median out of sample 71% of the time. Picking the single best setting is picking noise |
| Rank correlation, in-sample vs holdout Sharpe, 64 settings | 0.37 | Weak. Settings that did well before 2024 did only slightly better after |
| Deflated Sharpe, 64 trials, variance of the 64 Sharpes | 0.997 | Not meaningful on its own: the 64 settings hold mostly the same stocks, so their Sharpes barely vary and the implied noise bar (0.27) is far too low |
| The project's noise bar (research 064) | 2.99 | Not cleared by any setting |

## Findings

1. **Only the window is a real effect.** 9-12 month windows beat 3-6 month
   windows in-sample and again in the holdout (0.78-0.80 against 0.57-0.58).
   The paper's 12 months is already in the good region.
2. **Names held and rebalance frequency are noise.** Their holdout averages are
   flat (0.62-0.73), and the in-sample order does not survive.
3. **The chosen setting's holdout lead is probably luck.** 252/10/10 ranked
   first of 64 in the holdout, but its neighbours did not: 252/20/10 made 0.82,
   252/10/21 made 0.60. It sits on the edge of the grid (fewest names, fastest
   rebalance), holds 10 stocks, and pays three times the paper's costs. PBO
   0.71 says this way of choosing does not work on this data.
4. **Tuning did not beat the paper.** Walk-forward re-tuning earned less than
   leaving the paper's setting alone.

## Decision

**Keep the paper's setting: 12-month window, 30 names, monthly.** No change to
`india_papers.py` beyond making the window a parameter of the score
(`sharpe_momentum_over`), which leaves the paper's score unchanged. The
concentrated 252/10/10 is recorded here and not adopted.

**Confidence:** moderate that the window matters; high that nothing else in the
grid does; high that no setting clears the noise bar.

## Open questions

- The holdout years were seen by research 064. Only paper trading from
  2026-10-07 is truly unseen.
- No trial was recorded in the ledger (operator's instruction for this sweep);
  64 settings are a selection the ledger has not been charged for.
- The paper's own rules were never read (SSRN abstract only).
