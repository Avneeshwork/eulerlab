# 107 — GitHub Donchian channel: fixed NSE intraday screen

**Date:** 2026-10-15 · **Status:** backtested; negative net result

## Source and rule

The public [JamesRPowell/Donchain-Breakout repository](https://github.com/JamesRPowell/Donchain-Breakout)
contains a 5-minute script that enters long on a close above the prior 78-bar
high and exits on a close below the prior 39-bar low, with the channel
calculations shifted to exclude the signal bar. The source uses a 60-day
US-data sample, no transaction costs, and reports negative out-of-sample
Sharpe on several tickers. Its README cautions that this sample is too small
to establish general profitability. It is a lead for a fixed Indian test,
not proof of an edge.

## NSE adaptation

- Five fixed stocks: RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY.
- Aggregate local one-minute bars into 5-minute OHLCV, omitting the first
  09:15 print bin.
- Long entry after a completed close above the highest high of the prior 78
  bars; enter at the next contiguous 5-minute open.
- Exit after a completed close below the lowest low of the prior 39 bars;
  exit at the next contiguous open. Channel history continues across sessions,
  while positions are forced flat by 15:10.
- Allocate ₹200,000 per stock from ₹1,000,000 starting capital. Charge
  date-aware NSE intraday costs and 2 bp assumed slippage per side.
- Evaluate 2024-01-01 through 2024-11-30. Files with named end dates after
  the cutoff were excluded; no later price data was read.

This is a long-only, intraday adaptation of a continuous-position source. The
daily square-off is an explicit change. Donchian is structurally distinct from
the existing opening-range and Keltner rules, but remains in the same broad
price-breakout family.

## Result

| Measure | Result |
|---|---:|
| Common evaluation sessions | 224 |
| Round trips | 530 |
| Gross return / Sharpe | +6.94% / 1.387 |
| Net return / Sharpe | **−3.66% / −0.740** |
| Net maximum drawdown | −6.05% |
| Net winners / profit factor | 216 / 530 (40.8%) / 0.905 |
| Estimated fees and slippage | ₹104,421 |

Gross performance did not cover the modeled costs. Four of five stocks were
negative net; RELIANCE finished +₹6,065 while ICICIBANK and TCS were the
largest losses at roughly ₹17,900 each. This does not qualify as a profitable
candidate and is not a reason to tune 78/39 on the same period.

Reproduce with `make github-donchian-intraday`; results are stored in
`data/derived/github_donchian_stock_strategies.json`. Run `make library-sync`
to attach the measured result to the Strategy Library. Implementation:
`src/eulerlab/intraday/github_donchian_screen.py`.

## Limits

The five names are a present-day fixed universe. The test covers one calendar
year and uses assumed, not quote-calibrated, slippage. Minute data does not
show queues, partial fills or market impact. The source itself provides only
a short non-Indian intraday demonstration; this local result is a transfer
test, not a source replication.
