# 152 — A long-term consensus list: stocks at least 3 of the top 5 models pick (pre-registered)

**Written 2026-11-04 before the consensus strategy was backtested.**

## Question

The operator, 2026-11-04, on seeing that several stored strategies score above the 70:30 blend: "select top 5 models and recommend minimum 3 model common suggestion as list".

## The five, fixed now

The five highest full-period Sharpes among single long-term stock models with stored runs on 2016-01 to 2026-09, with two rules: no blend (blends reuse their parts), and the paper setting of volatility-adjusted momentum in place of the optimised one (best of 64 settings, PBO 0.71; research 067). They are:

| Id | Sharpe | Return | Max drawdown |
|---|---|---|---|
| `nse_github_stocks_on_the_move` | 1.06 | +682% | -29% |
| `india_sharpe_momentum` | 1.03 | +813% | -44% |
| `nse_github_weinstein_stage2` | 1.02 | +1,456% | -54% |
| `screen_quality_momentum` | 1.01 | +632% | -42% |
| `india_physical_momentum` | 0.93 | +769% | -49% |

## The rule, fixed now

`screen_consensus_3of5`: every 21 sessions, each of the five decides on the same view; a stock is held when 3 or more pick it, equal-weighted; none qualifying means cash. The list on the page is ranked by votes, then quality percentile, then 12-1 momentum. One configuration; it is run on 2016-2026 and on each half (2016-2020, 2021-2026) for the record, and will be shown whatever the result.

## Known before running

Four of the five are momentum rules that move together (HISTORY #44), so agreement among them is partly the same signal counted again; quality momentum is the only part using accounts. The parts were chosen because they had the best backtests, so the consensus inherits that selection.

## Results (appended 2026-11-04 after the runs; nothing above was edited)

Screening runs, Tier B, after Indian costs; NIFTYBEES 2016-01 to 2026-09 +221% before costs.

| Window | Sharpe | Return | Max drawdown | Fills |
|---|---|---|---|---|
| 2016-01 to 2026-09 | 0.89 | +626% | -56% | 2,759 |
| 2016-01 to 2020-12 | 0.48 | +52% | -56% | 1,281 |
| 2021-01 to 2026-09 | 1.33 | +455% | -31% | 1,461 |

- The consensus scored below each of its five parts over the full period (0.93 to 1.06). Requiring three votes concentrates the book in the few stocks every momentum rule holds at once, which deepened the 2020 fall (-56%).
- Its worse half (0.48) is below the 0.5 floor research 151 set for the swing blends, and below swing A's worse half (0.73). Its recent half (1.33) is the strongest of anything here; that is the half most likely to flatter a list chosen today.
- The operator asked for this list; it is shown as the long-term buy list with these numbers beside it.

## Confidence

Low that the consensus beats its parts; medium that it beat Nifty over 2016-2026 on this data.
