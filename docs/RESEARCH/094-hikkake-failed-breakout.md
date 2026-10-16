# Hikkake failed inside-bar breakout: NSE minute screen

## Question

Does the Hikkake false-breakout setup produce a usable intraday signal in the
fixed NSE minute-data sample after realistic estimated trading costs?

## Source and fixed rule

Dan Chesler's Hikkake is an inside bar followed by a bar that breaks the
inside-bar range in one direction. A bullish setup is followed by a lower high
and lower low; a bearish setup has a higher high and higher low. The source
places a stop entry one tick beyond the opposite inside-bar edge and expires
the entry after three bars. Oxford's tested exit uses a stop beyond the entire
pattern, an ATR(20) stop at six ATR, and a time exit. It states that holding
periods longer than ten bars were preferred. [Oxford Strategy's specification](https://oxfordstrat.com/trading-strategies/hikkake-pattern/)

The source tests 42 futures markets over 1980–2014. That result does not
establish profitability in NSE equities. [MQL5's Chesler rule summary](https://www.mql5.com/en/code/21137)
describes the confirmation requirement and three-bar expiry. A separate
US-stock test found no meaningful edge at a one-day holding period and said
its five-day result was the only favorable result; it also omitted costs.
[Decoding Markets' stock test](https://stocksoftresearch.com/bullish-hikkake-pattern/)

## NSE adaptation

## Deduplication against this repository

This was checked against the existing inside-bar continuation card (093) and
the initial-balance failure card. Hikkake instead requires the short
inside-bar range to break one way, then reverses only after a stop entry
through the opposite edge within three bars. It shares the broad false-breakout
family with initial-balance failure, but uses a local two-bar pattern and a
specific confirmation/expiry rule rather than fading a first-hour range.

- Five fixed stocks: RELIANCE, HDFCBANK, ICICIBANK, TCS, and INFY.
- Use the available one-minute archive only through 2024-11-30. Aggregate
  minutes after the 09:15 print to 5-minute OHLCV bars, requiring at least four
  observed minutes per bar.
- A strict inside bar is followed immediately by the bullish or bearish
  Hikkake bar. Enter one 0.05-point tick beyond the inside-bar edge if touched
  within the next three bars; fill at the trigger or a worse opening gap.
- Stop at the tighter of one tick beyond the formation extreme through the
  entry bar and the source's 6 x ATR(20) stop. The source has no profit target.
- Flatten at 15:10. Take at most one trade per stock/session. When the entry
  trigger and stop both touch in one five-minute bar, assume stop first.
- Use ₹200,000 notional per stock against ₹1,000,000 portfolio capital. Apply
  date-aware NSE intraday charges plus assumed 2 bp slippage per side.

This is a same-session adaptation of a source that prefers longer holding
periods. The five fixed stocks are not a point-in-time universe. OHLCV does not
reveal order-book liquidity or intrabar event order. No parameters were tuned
on this evaluation sample, and no data after 2024-11-30 were read.

## Result

| Measure | Fixed sample result |
| --- | ---: |
| Evaluation dates | 2024-01-01 to 2024-11-30 |
| Common sessions | 224 |
| Trades | 915 |
| Gross return | +1.42% |
| Gross profit factor | 1.057 |
| Net return | -15.31% |
| Net Sharpe | -6.811 |
| Net maximum drawdown | -15.31% |
| Net winning trades | 213 / 915 (23.3%) |
| Net profit factor | 0.569 |
| Estimated charges and slippage | ₹180,177.69 |

The small positive gross result is overwhelmed by the modeled costs. This
fixed NSE intraday adaptation therefore does not meet the objective of a
profitable strategy. Do not treat it as deployable or tune it against this same
window.

## Reproduction

Run `make hikkake-intraday` to write
`data/derived/hikkake_stock_strategies.json`. Run `make library-sync` to attach
the measured net daily curve to the Strategy Library card. Code:
`src/eulerlab/intraday/hikkake_screen.py`.
