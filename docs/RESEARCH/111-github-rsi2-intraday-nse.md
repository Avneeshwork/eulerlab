# 111 — GitHub Connors RSI(2): fixed NSE 5-minute screen

**Date:** 2026-10-15 · **Status:** backtested; negative net result

## Source and fixed rule

The [Jesse example-strategies RSI2 implementation](https://github.com/jesse-ai/example-strategies/blob/master/RSI2/__init__.py)
sets fast SMA to 5 bars, slow SMA to 200 bars and RSI to 2 bars. It enters
long above the slow SMA when RSI(2) is at most 10, short below the slow SMA
when RSI(2) is at least 90, then exits at the 5-bar SMA. The code describes a
generic chart-timeframe strategy and reports no independently verified NSE
intraday results.

## NSE adaptation

- Fixed stocks: RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY.
- Apply the source's bar-based periods to continuous 5-minute bars: SMA(200),
  Wilder RSI(2) and SMA(5). Indicators carry across sessions, as they do on a
  continuous chart; the 200-period trend therefore uses 200 five-minute bars,
  not 200 daily observations.
- Go long on a completed close above SMA(200) with RSI(2) <=10; go short below
  SMA(200) with RSI(2) >=90. Enter at the next contiguous 5-minute open.
- Exit long when a completed close is above SMA(5), and exit short below SMA(5),
  filling at the next open. Do not add a stop or target absent from the source.
  Force any remaining position flat at 15:10.
- Use at most one position per stock at once, with ₹200,000 notional per stock
  from ₹1,000,000 total capital. Apply date-aware NSE intraday costs plus 2 bp
  assumed slippage per side.
- Evaluate 2024-01-01 through 2024-11-30. The cutoff-aware loader excludes
  price files that cross the end date; this fixed development sample will not
  be tuned.

This exact RSI(2)/trend-SMA/fast-SMA rule is not a standalone card in the
current library. It sits in the broad mean-reversion family, but differs from
the existing extreme-minute fade and VWAP/OU rules by requiring a trend regime
and exiting on SMA(5).

## Result

| Measure | Result |
|---|---:|
| Common evaluation sessions | 224 |
| Round trips | 3,317 |
| Gross return / Sharpe | +5.54% / 1.739 |
| Net return / Sharpe | **−45.12% / −19.004** |
| Net maximum drawdown | −45.12% |
| Net winners / profit factor | 1,181 / 3,317 (35.6%) / 0.281 |
| Estimated fees and slippage | ₹653,190 |

The gross signal was positive, but over 3,300 round trips overwhelmed it with
modeled costs. This adaptation does not qualify as profitable and will not be
tuned against this sample.

Run `make github-rsi2-intraday` to reproduce. Output will be stored in
`data/derived/github_rsi2_pullback_stock_strategies.json`; `make library-sync`
attaches it to the Strategy Library. Implementation:
`src/eulerlab/intraday/github_rsi2_pullback_screen.py`.

## Limits

Five current stocks are not a point-in-time universe. The 5-minute version is
an adaptation of a timeframe-unspecified source. OHLCV lacks spread, depth,
queue position and partial fills, and assumed slippage may understate costs.
