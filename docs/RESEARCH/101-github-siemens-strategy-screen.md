# GitHub screen: ten Siemens India strategies

**Screen date:** 2026-10-15
**Disposition:** rejected for the intraday objective; all published signals are daily.
**Research Library record:** `github-siemens-10-strategies-screen`

## Repository claim and evaluation

The [NSE-Quant-Backtest repository](https://github.com/geekyyatharth/NSE-Quant-Backtest)
publishes ten technical systems on SIEMENS.NS daily prices from 2020 through
2024. It states that signals form at a day's close and execute at the next
session's open, with transaction costs, and divides 2020-2022 in-sample from
2023-2024 out-of-sample. Its listed rules are 20-day breakout with volume,
EMA pullback, gap follow-through, top-down EMA/RSI trend, ADX/EMA, SAR/DMI/volume,
Fibonacci retracement, RSI divergence, Bollinger/MACD/volume and EMA 20/50/200.

The README reports seven strategies with positive OOS Sharpe, up to 0.919, but
all fail the repository's stated pass criteria because each reported IS Sharpe
is negative. All full-period strategy returns also trail Siemens buy-and-hold.
The result is one daily stock sample, not minute-level or intraday evidence.

## Decision and deduplication

No candidate is added as an intraday strategy and no local test is run. The
entry/exit timing is daily, and the listed families duplicate breakout, gap,
EMA trend, oscillator, and mean-reversion studies already represented in this
library. Even if its daily results were independently verified, that would not
address the requested intraday goal.

This is source triage, not a judgment on whether any of the daily systems could
be useful for a separate swing or positional research track. The GitHub claim
is captured in the Research Library with the scope and validation caveats so it
does not re-enter the intraday queue as an apparently new signal.
