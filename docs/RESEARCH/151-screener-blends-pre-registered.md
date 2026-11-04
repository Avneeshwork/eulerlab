# 151 — Blending the screener's best models without overfitting (pre-registered)

**Written 2026-11-04 before any of the four blends below was backtested.**

## Question

The operator, 2026-11-04: use tree ranker and quality momentum at 30:70 for the long-term list; look for a combination for swing trading using volatility-adjusted momentum (top 10, every 2 weeks, optimised), Weinstein stage 2 with Mansfield RS, and the new models, "but ensure no overfitting".

## What is known before running

- Research 067 / the strategy's own notes: `india_sharpe_momentum_opt` is the best of a 64-setting sweep chosen on 2016-2023, PBO 0.71, and walk-forward re-tuning did not beat the paper's setting. Using it in a blend would carry that search into the blend. **The blends use the paper's setting, `india_sharpe_momentum` (top 30, monthly ranks), instead.**
- The 30:70 long-term weights were chosen by the operator after seeing research 150's results (quality momentum Sharpe 1.01, tree ranker 0.88). They are fixed here and not varied.
- Every part already has a stored screening run (research 150, the strategy map).

## The configurations (fixed; no others will be run)

| Id | Kind | Parts and shares | Rebalance |
|---|---|---|---|
| `screen_long_blend` | long | quality momentum 0.7, tree ranker 0.3 | 21 |
| `screen_swing_mom_weinstein` (A) | swing | Sharpe momentum (paper) 0.5, Weinstein stage 2 0.5 | 5 |
| `screen_swing_breakout_weinstein` (B) | swing | 52-week breakout 0.5, Weinstein stage 2 0.5 | 5 |
| `screen_swing_three` (C) | swing | Sharpe momentum, breakout, Weinstein, 1/3 each | 5 |

Shares are equal or the operator's; none is fitted.

## The rule for choosing the swing combination (fixed before running)

Each of A, B and C is run on 2016-01-01 to 2020-12-31 and on 2021-01-01 to 2026-09-30. **The combination shown as the swing list is the one with the highest Sharpe in its worse half.** Ties go to the one with fewer parts. The full-period Sharpe is reported but does not choose. All three results are shown, whichever wins. If no combination's worse half has a Sharpe above 0.5, the page says none is robust and shows no "chosen" mark.

## Sources

Research 150; research 067 (the optimised setting's PBO); HISTORY #44 (the momentum family is one bet).

## Confidence

Not applicable before running; results are appended below without editing the above.

## Results (appended 2026-11-04 after the runs; nothing above was edited)

Screening runs, Tier B, after Indian costs, liquid 250. NIFTYBEES 2016-01 to 2026-09: +221% before costs.

| Id | 2016-2026 Sharpe | Return | Max drawdown | 2016-2020 Sharpe | 2021-2026 Sharpe | Worse half |
|---|---|---|---|---|---|---|
| `screen_long_blend` | 0.98 | +575% | -46% | not run | not run | — |
| `screen_swing_mom_weinstein` (A) | 1.01 | +759% | -41% | 0.73 | 1.18 | **0.73** |
| `screen_swing_three` (C) | 0.91 | +458% | -35% | 0.64 | 0.99 | 0.64 |
| `screen_swing_breakout_weinstein` (B) | 0.86 | +412% | -39% | 0.55 | 0.97 | 0.55 |

**By the rule above, A is the swing list** (worse half 0.73, above the 0.5 floor). It also has the best full-period Sharpe, so the rule and the raw ranking agree here.

What this does and does not show:

- Every blend's first half is weaker than its second: 2016-2020 was hard for all of them, and that is the half that decides.
- The 70:30 long blend (0.98) did slightly worse than quality momentum alone (1.01): the tree ranker's 30% lowered Sharpe and raised turnover (6,496 fills against 3,103). The operator's weights are kept as set.
- A is two trend rules; it is close to one bet (HISTORY #44). C's lower drawdown (-35%) came with a lower Sharpe.
- Three configurations were tried here and six in research 150; none has spent a trial or faced the gate.

## Confidence

Medium for "A was more consistent than B and C on this data"; low for "A will beat Nifty": two halves are a weak test and the parts were chosen because they had done well.
