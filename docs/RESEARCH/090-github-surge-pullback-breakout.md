# GitHub surge and pullback breakout screen

**Screen date:** 2026-10-15. **Question:** test another distinct GitHub intraday rule on Indian stocks, document the result in the Research Library, and keep incompatible or duplicate candidates out of the test queue.

## Candidate tested

The [Ross Cameron-style strategy repository](https://github.com/woshishuaige2/ross-cameron-trading-strategy) describes a long-only sequence: a sharp surge, pullback, then the first green bar making a higher high. It also requires positive MACD(12,26,9), volume confirmation, a close above session VWAP and limits on selling pressure. Its `RossCameron-Strategy.py` code is the rule source. Fetch date: 2026-10-15.

The repository is aimed at US small-cap stocks, supports premarket trading and uses event/catalyst context. The local NSE archive has regular-session minute bars but not those premarket/catalyst fields. This is therefore a restricted price-only adaptation. The GitHub README, comments and configuration disagree: it states 1.5x or 2.0x relative volume in different places; a 0.3% or 3% minimum pullback; and describes a 1% or 2% stop floor. The screen freezes the code defaults of 2.0x relative volume and 0.3%-5% pullback, rather than choosing a value after viewing results. It uses a stop 1% below the pullback low and the documented 20% target. This mismatch lowers source confidence.

The coded rule requires a 2% high-low surge in a 5-20-bar segment, a 0.3%-5% pullback from the recent high, and a green higher-high trigger bar. It also requires positive MACD, close above session VWAP, mean volume of the last two bars at least twice the mean of the preceding up-to-eight bars, fewer than four red bars in the last five, and no high-volume topping wick. It enters at the next traded minute open. After entry, stop and target are checked before the source's candle-under-candle exit. If both stop and target are inside one minute, the stop is assumed first; a stop gap fills at the open.

## Local evaluation

The reader used RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY. The fixed evaluation is 2024-01-01 through 2024-11-30 (224 common sessions). Parquet objects with a named end date past 2024-11-30 are excluded. No later data is opened. Each name receives ₹200,000 notional. The cost model charges date-aware NSE intraday fees plus 2 bp assumed slippage on each side. Every position is closed by 15:10; at most one entry per name per session.

| Rule | Gross | Net | Net Sharpe | Trades | Estimated costs |
|---|---:|---:|---:|---:|---:|
| Surge/pullback first higher high | -0.08% | **-0.10%** | -1.061 | 1 | ₹197 |

The one trade was HDFCBANK on 2024-06-04: entry ₹763.30, exit ₹760.10 after a candle-under-candle trigger; the 20% target was not reached. One trade is far too little evidence to claim an edge. The result is negative and this screen does not qualify as one of the five strategies sought. Do not relax thresholds on this same test to manufacture a larger sample.

Reproduce with `make github-momentum-pullback-intraday`; sync the Research Library result with `make library-sync`. The output is `data/derived/github_momentum_pullback_stock_strategies.json`.

## Other new GitHub candidates reviewed

| Repository | Candidate | Disposition |
|---|---|---|
| [Traders-systems/TradingBot-A](https://github.com/Traders-systems/TradingBot-A) | Peer-confirmed higher-timeframe levels; peer-confirmed trend continuation; multi-regime top-tier adaptive | The README exposes many knobs and does not provide a single falsifiable NSE configuration or verified results; several mechanisms overlap trend, VWAP, key-level and squeeze cards. Do not treat its feature-rich configuration as a separate established edge. |
| [sam-bateman/trading-orb](https://github.com/sam-bateman/trading-orb) | Volume-filtered opening-range breakout | ORB is already represented, and the source is a US equity system with repeated parameter selection. Excluded as duplicate. |
| [pderer/orb_strategy](https://github.com/pderer/orb_strategy) | Rank US stocks by relative opening volume, then take 5-minute ORB | ORB is already represented. The stock filters and universe are US-specific; do not count the volume rank as an independent signal without an incremental test. |
| [fmzquant/strategies](https://github.com/fmzquant/strategies) | Relative volume + RSI breakout/exit | The published sample is a Binance BTC one-hour strategy. It is neither Indian equity intraday evidence nor a new RSI/momentum family here. |
| [rxsinx/relative-volume](https://github.com/rxsinx/relative-volume) | Relative-volume strong-start and RSI divergence | Its stated signals use daily and 15-minute bars and Yahoo data; entry/exit execution for a one-minute NSE strategy is not specified. Not tested. |
| [NISHCHAY026/premarket-trader](https://github.com/NISHCHAY026/premarket-trader) | Walk-forward ML selection of US premarket gap movers | The reported strategy depends on premarket, float and catalyst data, while its README says free daily bars approximate an intraday method. The gap family is already in the library; this is not minute-level Indian evidence. |
| [gvillebandit01/Pine_script_tradingview](https://github.com/gvillebandit01/Pine_script_tradingview) | Multi-indicator score (ADX, RSI, MACD, RVOL, pullback, EMA and key-level checks) | Too many correlated conditions and configurable presets to isolate an independent hypothesis; source does not provide a reproducible NSE costed test. Excluded as a tuned indicator bundle. |
| [mementum/backtrader relative-volume sample](https://github.com/mementum/backtrader/tree/master/samples/relative-volume) | Intraday relative-volume-by-time-of-day indicator | Indicator example, not a complete entry/exit strategy or evidence of alpha. Could support a future execution/data feature, but is not registered as a profitable strategy. |
| [voletiramu/nse-fno-1min-data](https://github.com/voletiramu/nse-fno-1min-data) | NSE F&O 1-minute archive and mentions of third-party strategy labels | Data repository and unsourced strategy references do not supply a new deterministic rule. We did not fetch or copy this dataset. |

Including the tested source above, ten repositories were screened. Duplicates, vague rule sets and missing-data candidates remain attached to this Research Library note so they are not silently lost or relabeled as new profitable systems.

## Limits and next data

The selected five large liquid names are not the US low-float small-cap universe for which the source was designed. The adaptation has one trade and cannot support a statistical conclusion. The source repository's threshold contradictions are preserved above. Costs include estimated exchange charges and assumed slippage, but no queue position, spread replay, partial fills or market impact.

Reassess this candidate only if a point-in-time Indian stock universe and pre-open/event fields support a separate pre-registered test. The current negative one-trade screen is not enough to claim profitability, and its defaults should not be tuned against this evaluation window.
