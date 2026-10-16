# 109 — GitHub engulfing + volume + RSI: NSE screen

**Date:** 2026-10-15 · **Status:** backtested; negative net result

## Source and fixed rule

The [public GitHub backtester](https://github.com/kavyansh34/Engulfing_candle_backtester)
is a BTCUSDT example. Its stated setup combines engulfing candles with RSI(14)
below 40 for longs and above 60 for shorts, signal volume above EMA(14), and a
1:5 risk/reward target. It does not report verified NSE results, and it omits
fees and slippage.

The source implementation has ambiguous engulfing checks: candle color is not
consistently confirmed. Its long stop also takes the higher of the two lows,
and it does not check the entry candle for stop or target fills. This screen
independently implements a strict opposite-color body engulfing pattern and
uses the lower pair low for a long stop (higher pair high for a short).

## NSE adaptation

- Fixed stocks: RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY.
- Use complete 5-minute bars from one-minute OHLCV. The bullish candle must
  open at or below the previous bearish candle's close and close at or above
  its open; reverse the colors and inequalities for a bearish setup.
- Require signal-bar volume above the volume EMA(14) computed through the
  preceding bar, and RSI(14) below 40 for a long or above 60 for a short.
- Enter at the next contiguous 5-minute open. Use the outside extreme of the
  two pattern bars as the stop and a fixed 5R target.
- Risk 1% of each ₹200,000 stock sleeve, capped at its ₹200,000 notional. Take
  at most one trade per stock per session and flatten by 15:10.
- If both stop and target trade in one bar, assume the stop happens first. A
  stop gapped through fills at the open. Costs use date-aware NSE charges plus
  2 bp assumed slippage per side.
- Evaluation window: 2024-01-01 through 2024-11-30. This is a fixed development
  sample, not a future holdout; it will not be tuned against this window.

## Result

| Measure | Result |
|---|---:|
| Common evaluation sessions | 224 |
| Round trips | 360 |
| Gross return / Sharpe | −0.02% / −0.010 |
| Net return / Sharpe | **−6.86% / −5.088** |
| Net maximum drawdown | −6.86% |
| Net winners / profit factor | 89 / 360 (24.7%) / 0.519 |
| Estimated fees and slippage | ₹70,759 |

Gross returns were approximately flat before costs, and modeled costs turned
the result materially negative. The rule does not qualify as profitable and
will not be tuned against this sample.

Run `make github-engulfing-intraday` to reproduce. The result will be stored
in `data/derived/github_engulfing_stock_strategies.json`; `make library-sync`
attaches it to the Strategy Library. Implementation:
`src/eulerlab/intraday/github_engulfing_screen.py`.

## Limits

Five current stocks are not a point-in-time universe. Minute OHLCV does not
contain spread, market depth, queue position or partial fills. The assumed
slippage and stop-first intrabar ordering can affect outcomes. One fixed
evaluation period is not enough to establish future profitability.
