# GitHub EMA(5/15) crossover: costed NSE stock adaptation

## Candidate and source

The public repository [Quantitative Trading System – NIFTY](https://github.com/mohanyadu/Quantitative-Trading-System-NIFTY-5-Min-)
describes a 5-minute EMA(5/15) crossover with an HMM market-regime gate. It
enters at the next candle open and exits/reverses at the next opposite cross.
The README says its HMM uses option IV, IV spread, put-call ratio, ATM Greeks,
futures basis, and spot returns. It reports baseline returns of −2.35% in
training and −0.63% in test, before costs; its XGBoost filter produced zero
trades. The README lists transaction costs and broader validation as future
work. The repository had five commits and zero stars when reviewed, so its
claims are weak, unverified source evidence rather than research validation.

## Deduplication and data blocker

The repository's crossover is different from the existing NSE EMA/MACD
pullback card: it trades the cross itself and reverses on the opposite cross,
without a pullback entry. It is also distinct from the library's ORB,
opening-range, and inside-bar setups.

The NSE minute archive supports the price-only crossover but lacks the
repository's option-chain IV, IV spread, PCR, Greeks, and futures-basis inputs.
The complete HMM-filtered source strategy therefore remains **data blocked**.
To make progress with available data, this screen tests only the source's
price-only EMA(5/15) baseline. It does not synthesize or replace the regime
filter.

## Fixed screen

- Universe: RELIANCE, HDFCBANK, ICICIBANK, TCS, and INFY.
- Build 5-minute OHLCV bars from the local one-minute archive, skipping the
  09:15 print bin and accepting bars with at least four observed minutes.
- Calculate recursive EMA(5) and EMA(15) continuously per symbol, warmed using
  data available before 2024. When the fast EMA crosses above/below the slow
  EMA, enter long/short at the next contiguous 5-minute open. Close and reverse
  on the next opposite cross.
- Carry no position overnight; flatten at 15:10. Split ₹1,000,000 equally
  across the five names. Use date-aware NSE intraday charges plus assumed
  2 bp slippage per side.
- Fixed evaluation: 2024-01-01 through 2024-11-30. The loader excludes parquet
  objects whose end date crosses 2024-11-30. No settings were searched.

The five names are a fixed large-cap set without point-in-time membership
correction. EMA crossovers create many fills; the screen does not model
market impact or quote-level execution. The source's HMM is not part of this
measured configuration.

## Result

| Measure | Fixed sample result |
| --- | ---: |
| Common evaluation sessions | 224 |
| Completed round trips | 5,320 |
| Fills | 10,640 |
| Gross return | −1.95% |
| Gross profit factor | 0.987 |
| Net return | −65.72% |
| Net Sharpe | −16.444 |
| Net maximum drawdown | −65.72% |
| Net winning trades | 1,266 / 5,320 (23.8%) |
| Net profit factor | 0.506 |
| Estimated charges and slippage | ₹1,047,631.68 |

The price-only adaptation fails after costs and is not a profitable strategy.
The original source also reports negative test performance before costs, and
its full HMM-filtered results remain unreproducible from available equity
OHLCV due to the missing feature histories.

## Reproduction

Run `make github-ema-crossover-intraday` to write
`data/derived/github_ema_crossover_stock_strategies.json`. Run
`make library-sync` to attach its costed daily curve to the Strategy Library.
Implementation: `src/eulerlab/intraday/github_ema_crossover_screen.py`.
