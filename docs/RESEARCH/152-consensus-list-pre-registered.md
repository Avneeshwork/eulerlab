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
