# Multi-timeframe Supertrend re-alignment with volume confirmation

## Source rule and evidence

LeadFinn's [Supertrend strategy page](https://leadfinn.co/strategies/supertrend)
describes a setup where a 1-hour Supertrend is bullish, the 15-minute
Supertrend temporarily turns bearish and then flips bullish again, and
15-minute volume crosses above its 20-period average. It gives a 1:2 target
example with the 15-minute Supertrend line as the stop. The page says to avoid
new entries before 09:45 and raw Supertrend flips lose after costs. It reports
raw 15-minute results of −19.3% over 1,573 trades with a 1% stop/2% target,
and in a separate three-year table −44.5% with a 1.5% stop/3% target. Those
are source-engine results for raw flips, not for this multi-timeframe setup;
the page does not report a separate result for the setup tested here. The
source is practitioner research, not a peer-reviewed study.

## Deduplication

No existing card implements a higher-timeframe Supertrend regime with a
lower-timeframe bearish-to-bullish re-alignment and volume-cross filter. It is
distinct from the repo's EMA/MACD pullback, VWAP/noise-area momentum, raw
opening-range breakouts, and inside-bar/Hikkake patterns. The broad concept is
trend continuation, but the signal and filters differ materially.

## Fixed NSE implementation

- Universe: RELIANCE, HDFCBANK, ICICIBANK, TCS, INFY.
- Convert the local one-minute archive into 15-minute and 60-minute OHLCV bars,
  excluding the 09:15 print. Bars need at least 80% of their constituent
  minute observations.
- Calculate recursive Wilder ATR(10) Supertrend with multiplier 3 on both
  timeframes, continuously over the available pre-evaluation history. Use
  only a fully completed hourly bar for the regime gate.
- After 09:45, enter long when the 15-minute Supertrend changes from bearish
  to bullish, the latest completed hourly Supertrend is bullish, and 15-minute
  volume crosses above its trailing 20-bar mean.
- Enter at the next 15-minute open. Stop at the 15-minute Supertrend line on
  the signal close; target 2R. If stop and target both touch in one 1-minute
  bar, assume stop first. At most one entry per stock/session; flatten at
  15:10.
- Allocate ₹200,000 notional per name from ₹1,000,000 total capital. Apply
  date-aware NSE intraday fees plus assumed 2 bp slippage per side.
- Fixed evaluation: 2024-01-01 to 2024-11-30. The reader never opens files
  whose named end date crosses 2024-11-30. No parameters were optimized.

These are explicit implementation choices where the source is not fully
mechanical: same Supertrend settings (10,3) on both timeframes, next-bar
execution, long-only direction, one entry per session, and a 2R target. They
were frozen before screening. The five names are not point-in-time constituents
and the assumed slippage is not quote-level market impact.

## Result

| Measure | Fixed sample result |
| --- | ---: |
| Common sessions | 224 |
| Completed trades | 29 |
| Gross return | +0.08% |
| Gross profit factor | 1.075 |
| Net return | −0.49% |
| Net Sharpe | −0.969 |
| Net maximum drawdown | −0.69% |
| Net winners | 13 / 29 (44.8%) |
| Net profit factor | 0.648 |
| Estimated charges and slippage | ₹5,713.37 |

This is a small sample with negative net performance. It does not count toward
the five-profitable-strategy objective. Do not tune parameters against this
window.

## Reproduction

Run `make supertrend-alignment-intraday` to write
`data/derived/supertrend_alignment_stock_strategies.json`. Run
`make library-sync` to attach the measured curve to the Strategy Library.
Code: `src/eulerlab/intraday/supertrend_alignment_screen.py`.
