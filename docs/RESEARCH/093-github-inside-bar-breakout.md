# GitHub inside-bar breakout: NSE minute screen

**Screen date:** 2026-10-15
**Status:** independently tested; rejected after costs. This does not count toward the five profitable-strategy goal.

## Source and rule

The [FMZ GitHub strategy](https://github.com/fmzquant/strategies/blob/master/%E5%86%85%E9%83%A8%E6%94%B6%E6%95%9B%E7%AA%81%E7%A0%B4%E7%AD%96%E7%95%A5Inside-Bar-Breakout-Strategy.md) defines an inside bar as a candle whose high and low are strictly within the preceding candle. It then trades a subsequent break, with a stop and target. Its PineScript code mixes inside and outside bars, uses percentage target/stop inputs, and does not give independently verifiable results. A separate mechanical screen reports that inside-bar breakouts had PF 0.98 and negative mean net performance across four non-Indian markets, with only one market profitable; this is a weak prior, not NSE evidence. [Independent screen](https://secuora.net/verified/inside-bar-breakout).

The frozen NSE adaptation uses 5-minute bars. A strict inside bar must be followed immediately by a completed 5-minute close outside the inside bar's own range. The entry is the next 5-minute open; the stop is the opposite inside-bar extreme; the target is 2R from the actual entry. If the next open makes risk non-positive, skip. It permits one trade per stock per session, flattens at 15:10, and assumes stop-first when both stop and target appear in one bar. This close-confirmed next-open execution can miss an intrabar breakout but avoids filling at a signal price that was only knowable after the bar closed.

## Local evaluation

The test used RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY over 2024-01-01 through 2024-11-30 (224 common sessions). The cutoff-aware reader excludes files whose named end passes 2024-11-30; no later data was opened. No parameter fitting was done. Each name received ₹200,000 notional on ₹1,000,000 total fixed capital. Costs include date-aware NSE intraday charges and assumed 2 bp slippage per side.

| Rule | Gross return | Net return | Net Sharpe | Net max drawdown | Trades | Net trade win rate / PF | Estimated costs |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5-minute inside-bar close break, structural stop, 2R | -1.02% | **-20.40%** | -9.065 | -20.49% | 1,106 | 33.1% / 0.548 | ₹217,793 |

The pattern had near-zero gross expectancy (about −₹9 per trade before costs) and the expected execution charges turned it into a clear loss. All five symbol-level net totals were negative; ICICIBANK was least negative at −₹27,222, while RELIANCE lost −₹64,840. The result is not a case for adjusting the R target or adding filters on the same evaluation period.

Reproduce with `make inside-bar-intraday`; the output is `data/derived/inside_bar_stock_strategies.json`. `make library-sync` writes the measured curve to the Strategy Library; this card and its source are linked in the Research Library record.

## Limits

- Five fixed names leave survivorship and universe-selection bias.
- A four-observation minimum is used for each 5-minute bar; missing or sparse bars are skipped.
- Five-minute OHLC cannot determine whether a stop or target traded first, so collisions resolve to the stop.
- The 2 bp per-side slippage is an assumption, not calibrated to historical quotes or market impact.
- The local result is a single frozen screen, not a live-execution estimate or an untouched post-2024 holdout.
