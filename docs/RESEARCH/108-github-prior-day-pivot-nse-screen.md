# 108 — GitHub prior-day floor pivot breakout: NSE screen

**Date:** 2026-10-15 · **Status:** backtested; negative net result

## Source and fixed rule

The [FMZ community strategy](https://github.com/fmzquant/strategies/blob/master/%E5%8A%A8%E6%80%81%E6%94%AF%E6%92%91%E9%98%BB%E5%8A%9B%E5%9B%9E%E6%B5%8B%E7%AD%96%E7%95%A5Dynamic-Pivot-Point-Backtest-Strategy.md)
computes floor-trader levels from the prior session:

```text
PP = (prior high + prior low + prior close) / 3
R1 = 2 * PP - prior low
S1 = 2 * PP - prior high
```

It goes long above R1, short below S1, and keeps the position while price is
between those levels. The code is an educational example, not a verified
profitability result. Its sample configuration is a 15-minute Binance BTC
strategy.

## NSE adaptation

- Fixed five stocks: RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY.
- Compute R1/S1 from the immediately prior NSE session's minute OHLCV-derived
  high, low and close. Do not use current-day data to form the levels.
- On a completed 5-minute close above R1, go long at the next contiguous
  5-minute open; below S1, go short. Hold through closes between thresholds.
- Reverse at the next open after a close beyond the opposite threshold.
- Force positions flat by 15:10; no overnight positions.
- Allocate ₹200,000 per stock from ₹1,000,000 total capital. Apply date-aware
  NSE intraday charges and 2 bp assumed slippage per side.
- Evaluate 2024-01-01 through 2024-11-30. Price files with named end dates
  after the cutoff are excluded; no later data was read.

This uses previous-session pivots rather than the current-session opening
range, so the level construction differs from the existing ORB cards. It is
still a generic level breakout in the broader trend/breakout family.

## Result

| Measure | Result |
|---|---:|
| Common evaluation sessions | 224 |
| Round trips | 816 |
| Gross return / Sharpe | +12.14% / 1.867 |
| Net return / Sharpe | **−4.50% / −0.701** |
| Net maximum drawdown | −10.87% |
| Net winners / profit factor | 366 / 816 (44.9%) / 0.928 |
| Estimated fees and slippage | ₹160,678 |

Two stocks finished positive net, while three were negative. Gross results did
not cover costs. This rule does not qualify as profitable and will not be
tuned against the same evaluation period.

Run `make github-pivot-intraday` to reproduce the backtest. The result is
stored in `data/derived/github_pivot_stock_strategies.json`; `make library-sync`
attaches it to the Strategy Library. Implementation:
`src/eulerlab/intraday/github_pivot_breakout_screen.py`.

## Limits

The sample is one evaluation period and uses five fixed present-day stocks,
not point-in-time constituents. Minute OHLCV lacks bid/ask, depth and queue
position. The 2 bp slippage on each side is assumed rather than estimated from
historical quotes. Frequent reversals make the after-cost result sensitive to
execution assumptions.
