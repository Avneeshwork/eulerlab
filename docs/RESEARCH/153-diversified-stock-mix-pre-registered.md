# 153 — A stock-only mix across strategy categories (pre-registered)

**Written 2026-11-04 before the mix was backtested.**

## Question

The operator, 2026-11-04: the screener's lists all come from similar strategies; diversify across categories, aiming at a positive return in every one of the last 10 years and 25% a year. Then: "keep only stocks nothing else", and "Always invested" (no cash filter).

## What is known before running

- Of 64 stored strategies with 2016-2025 history, 2 had no losing calendar year (both about 11% a year), none had no losing year with 25% a year, and none made 25% in every year (measured 2026-11-04).
- Every long-only stock strategy's daily returns correlate 0.6 to 0.85 with Stocks on the Move: they all hold Indian stocks and share the market's bad years (2018 most of all). Mixing them smooths less than mixing assets would.
- So the target is not expected to be met; the mix is tested for what it does to the worst year and the number of losing years.

## The configuration (one; no others will be run)

`screen_stock_mix`: one third each of `nse_github_stocks_on_the_move` (momentum), `india_low_tvol36` (low volatility) and `screen_value_momentum_quality` (value and quality from accounts), always invested, rebalanced every 21 sessions. Equal thirds, not fitted weights.

## How it is judged (fixed now)

Calendar-year returns 2016-2025 and the number of losing years; return a year; worst fall; Sharpe on 2016-2026 and on each half (2016-2020, 2021-2026); against NIFTYBEES. Shown whatever the result.

## Addendum, written 2026-11-04 before either configuration's result was read

The operator: "We can add goldbees and silver bees too but keep very less weightage". A second configuration, fixed now:

`screen_stock_mix_gold`: 90% `screen_stock_mix`, 10% GOLDBEES (`screen_hold_goldbees`), rebalanced every 21 sessions. SILVERBEES is left out of the backtest because its prices start on 2022-05-10; it would change the strategy part-way through the test. Judged the same way as the stock mix, and both are shown.

