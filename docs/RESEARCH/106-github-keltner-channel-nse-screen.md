# 106 — GitHub Keltner Channel breakout: fixed NSE screen

**Date:** 2026-10-15 · **Status:** backtested; rejected after costs

## Source and fixed rule

The [cloudQuant/backtrader Keltner strategy test](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility/test_108_keltner_channel_strategy.py)
describes a simple long-only breakout: enter when a completed close is above
the Keltner upper band and exit when a completed close falls below the EMA
middle line. The example sets period 20 and ATR multiplier 2.0. It is a code
example, not published evidence of returns in India.

I translated the rule to 5-minute NSE bars:

- EMA(20) and Wilder ATR(20), with the upper band at EMA + 2 ATR.
- Enter at the next contiguous 5-minute open after the close is above the
  upper band; exit at the next open after a close falls below EMA(20).
- Long only, no overnight positions, square off at 15:10.
- Five fixed stocks: RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY. Allocate
  ₹200,000 per stock from ₹1,000,000 capital.
- Use date-aware NSE intraday fees and 2 bp assumed slippage per side.
- Evaluate 2024-01-01 through 2024-11-30. Files with named end dates after the
  cutoff are excluded; no later price data was read.

The source discusses volume confirmation as an optional improvement; this
screen leaves it out to test the simple core rule. The Keltner method is a new
source/configuration in this library, but it sits within the broad breakout
family and is adjacent to the earlier Bollinger squeeze screen.

## Result

| Measure | Result |
|---|---:|
| Common evaluation sessions | 224 |
| Round trips | 956 |
| Gross return / Sharpe | +2.57% / 0.603 |
| Net return / Sharpe | **−15.04% / −3.684** |
| Net maximum drawdown | −15.75% |
| Net winning trades / profit factor | 309 / 956 (32.3%) / 0.690 |
| Estimated fees and slippage | ₹188,270 |

All five individual stock totals were negative after modeled costs. The small
positive gross result did not survive turnover costs, so this candidate does
not count toward the five profitable intraday-strategy goal. Do not optimize
it against this same window.

Reproduce with `make github-keltner-intraday`; output is
`data/derived/github_keltner_stock_strategies.json`. Run `make library-sync` to
attach the measured result to the Strategy Library. Implementation:
`src/eulerlab/intraday/github_keltner_screen.py`.

## Deduplication and limitations

The exact Keltner channel and EMA exit are not in an existing library card.
The signal is still a close-confirmed price breakout, so it overlaps the
broader trend/breakout family. Earlier distinct GitHub screens for opening
range, Bollinger squeeze, EMA crossover, inside-bar, Hikkake and Supertrend
are linked in Research 088–096; this does not rename those tests.

The universe is five present-day liquid names, not point-in-time constituents.
The 2024 evaluation is a single fixed period. OHLCV does not include bid/ask,
queue position or partial fills; 2 bp per-side slippage is an assumption.

## Next GitHub candidates

The [Donchian 78/39 source](107-github-donchian-intraday-nse-screen.md) has
now been screened separately. The [Indian OHL example](https://github.com/arshadakl/intraday-trading-bot)
combines an opening gap, O=H/O=L pattern and first-15-minute breakout, but
overlaps the existing gap and opening-range cards and depends on pre-market
volume not present in this archive. The [VWAP breakout-retest example](https://github.com/PineGen-AI/vwap-breakout-retest-trend-strategy)
likewise overlaps existing VWAP continuation research. I screened these as
duplicates rather than adding cosmetic variants.
