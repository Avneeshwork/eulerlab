# Gold and Indian stock intraday strategy screen

**Screen date:** 2026-10-15
**Data cutoff:** 2024-12-31. No later observations were used.
**Purpose:** identify source-backed minute strategies, check the existing library for duplicates, and separate executable rules from ideas that need unavailable data or a more exact source rule.

## Findings

This review does not support a claim that any of these strategies is expected to be highly profitable. Several papers report gross or costless effects, and studies on Chinese or US markets do not establish profitability on NSE stocks or MCX Gold. The strongest candidates that could be screened with current data are an extreme-minute reversal rule on NSE equities and moving-average rules on the listed Gold ETF GOLDBEES. The latter is not MCX futures.

Existing local work already tests Indian ORB, gap continuation/fade, opening and closing momentum, VWAP/noise-area momentum, OU reversion, volume surge, cross-sectional extreme fade, Heston same-time momentum, and end-of-day reversal. Those families are not counted as new implementations here. See research notes [071](071-two-intraday-papers-on-niftybees.md), [076](076-five-indian-intraday-rules.md), [077](077-more-intraday-stock-rules-for-india.md), [078](078-two-us-stock-rules-on-indian-stocks.md), and [083](083-intraday-stock-data-sources-india.md).

## Candidate screen

| # | Source and rule family | Rule/data described by source | Deduplication and local status |
|---|---|---|---|
| 1 | Rif & Utz (2021), [Short-term stock price reversals after extreme downward price movements](https://doi.org/10.1016/j.qref.2021.05.004) | Nasdaq-100, 2014–2019, nanosecond data. An extreme one-minute loss, defined as an event expected once per 1,000 one-minute intervals, is followed by a one-minute reversal averaging 31% of the drop; stronger in larger and more liquid stocks. | Distinct from Heston’s cross-sectional same-clock continuation and Tripathi/Aggarwal’s 30-minute cross-sectional fade. Feasible as a fixed threshold learned only on 2022–2023 and frozen for 2024; that is a transparent India adaptation, not an exact replication. Implemented below. |
| 2 | Naga et al. (2024), [Decision Trees for Intuitive Intraday Trading Strategies](https://arxiv.org/abs/2405.13959) | NSE Nifty-50 constituents, 1-minute data, 2022–2024. Nine technical features feed a Gini decision tree (depth 4) predicting the next minute’s return sign; the paper shifts signals one bar. Reported results omit trading costs and its gap interpolation is unsuitable for execution. | Distinct nonlinear classifier. Implemented as a five-stock, no-gap adaptation with an explicit ADX proxy and 210-minute intraday feature warm-up. Gross +70.09%; net account depleted after 182,050 events and ₹35.92m estimated cost on ₹1m starting capital. Not a paper replication. |
| 3 | Batten, Ciner & Lucey (2018), [Does intraday technical analysis have value in precious metal markets?](https://c.mql5.com/forextsd/forum/174/does_technical_analysis_beat_the_market__evidence_from_high_frequency_trading_in_gold_and_silver.pdf), SMA | Five-minute OTC gold/silver, 2008–2014. Simple moving-average trading rules; paper evaluates 66,297 rules per market and warns about data mining. Popular short/long settings were not a reliable positive gold result. | Distinct from existing intraday momentum/reversion. Fixed popular 1/50, 1/100, 1/150, 1/200 pairs are screened on GOLDBEES five-minute bars, explicitly as ETF proxy. |
| 4 | Batten et al. (2018), EMA | Same source, exponential moving-average crossover family. | Same source family as #3; reported separately as a filter form, not claimed as an independent discovery. Screened with the same fixed horizons and costs. |
| 5 | Batten et al. (2018), WMA | Same source, weighted moving-average crossover family. | Same source family as #3; reported separately as a filter form, not claimed as an independent discovery. Screened with the same fixed horizons and costs. |
| 6 | Jin (2022), [Performance of intraday technical trading in China’s gold market](https://doi.org/10.1016/j.intfin.2021.101481) | Five-minute most-active SHFE gold futures, March 2018–March 2021; explicitly considers snooping, costs and out-of-sample performance. The accessible source summary does not specify a single untouched rule sufficiently to reproduce. | Gold-specific but not enough exact rule detail for a faithful implementation. China futures are not MCX futures; mark source as screened, rule blocked pending full article/specification. |
| 7 | Zheng & Luo (2024), [Intraday reversal in commodity futures and options](https://doi.org/10.1016/j.pacfin.2024.102534) | One-minute Chinese commodity futures/options; reversal and overnight/opening factors, with options-market mechanisms. | Distinct market, but the rule depends on options/open-interest and cross-market data absent from the archive. Existing generic reversal rules make a price-only port duplicative; blocked. |
| 8 | Christie-David, Chaudhry & Koch (2000), [Do macroeconomic news releases affect gold and silver prices?](https://www.sciencedirect.com/science/article/abs/pii/S0148619500000308) | COMEX gold/silver reaction around US macro announcements, 1992–1995. | Event strategy needs point-in-time release timestamps and consensus surprises. No such event archive is available locally; no direction/threshold inferred from the abstract. Blocked. |
| 9 | Hauptfleisch, Putniņš & Lucey (2016), [Who Sets the Price of Gold? London or New York](https://doi.org/10.1002/fut.21736) | Intraday price discovery between London and New York gold venues. | This is price discovery evidence, not a standalone executable trading rule. Synchronized COMEX/London quotes are unavailable. Excluded from code rather than inventing a strategy. |
| 10 | “What triggers intraday price jumps and co-jumps in gold?” (2025), [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1057521925004673) | Five-minute CME gold futures and GLD; examines macro news, jumps, and co-jumps. | News-event study, not an exact strategy rule in the available text. CME and point-in-time news/surprise data are absent. Blocked. |
| 11 | Ma et al. (2025), [The “night effect” of intraday trading](https://doi.org/10.1016/j.gfj.2025.101084) | Chinese gold/silver futures: the opening half-hour predicts later returns, with day/night session dependence. | The first-half-hour predictor is substantially the same family as Gao/Heston already tested locally. Not counted as new. |
| 12 | MCX Gold/Crude/INRUSD volatility spillover (2023), [Journal of Open Innovation](https://doi.org/10.1016/j.joitmc.2023.100094) | Thirty-minute volatility spillovers, 2021–2022. | A volatility relationship without a directional entry/exit rule; no valid trading strategy can be inferred. MCX minute futures history is absent. |
| 13 | Sen (2022), [Efficient Pair-Trading Strategies for the Indian Stock Market](https://arxiv.org/abs/2211.07080) | Indian equity pairs using daily prices, with a daily train/test design. | Not minute-level. Daily pair trading is outside this request and is not re-labeled as an intraday strategy. |

This is 10+ distinct source-backed candidates/evidence tracks, not 10 independently validated profitable algorithms. Three moving-average variants are one literature family. Several candidates are explicitly blocked rather than reverse-engineered from an abstract.

## Data and test protocol

- At the time of this screen, MCX Gold futures minute history was not in the archive. A later fetch of the live `GOLD26DECFUT` contract and its limited backtest are documented in [086](086-mcx-gold-futures-minute-backtest.md). `MCXGOLDEX` remains an index, not a tradable future. Kite's expired-contract continuous history is daily, so the available Zerodha data does not support a five-year minute futures backtest or expiry-aware roll test.
- GOLDBEES has Kite minute bars from 2021-08-19 in B2. It is an exchange-traded Gold ETF proxy, with equity fees and ETF trading behavior; it is not spot gold or MCX futures.
- NSE cash one-minute data is available for 420 symbols. The stock experiment uses a fixed, explicitly named liquid-stock sample and reports 2024 only as an evaluation period; 2022–2023 is used only to establish the extreme-return threshold. It does not inspect 2025 onward.
- Execution is delayed to the next traded minute/bar. Missing prices are not interpolated. Equity charges use the project’s NSE intraday cost router, plus a stated 2 bps per-side slippage assumption for stocks and 1 bp for GOLDBEES. Results should be treated as a screening estimate because minute OHLC cannot reveal queue position or true spread.
- Strategy settings are source-fixed. No best-of-grid selection is presented as out-of-sample evidence. The published Gold paper itself tests a large rule universe, so the small predeclared subset here must be interpreted in that context.

## Fixed-screen results

The run used 224 regular sessions in the evaluation window, 2024-01-01 through 2024-11-30. These are screening results, not holdout results and not live execution estimates.

| Candidate | Gross return | Net return | Net Sharpe | Max drawdown | Orders/events | Estimated costs |
|---|---:|---:|---:|---:|---:|---:|
| Extreme one-minute reversal, five stocks | +2.80% | -10.73% | -3.30 | -10.89% | 712 events | ₹140,492 |
| Depth-four decision tree, five stocks | +70.09% | -100.00% (account depleted) | not meaningful after ruin | -100.00% | 182,050 events | ₹35.92m |
| Gold ETF MA rules, 12 fixed settings | +10.28% to +20.79% | -17.43% to -51.33% | -2.86 to -7.99 | -20.66% to -52.09% | 4,226 to 12,058 fills | ₹1.27m to ₹3.61m |

The small extreme-move gross edge did not cover fees and assumed slippage. The decision tree traded about 813 one-minute round trips a session; its gross result did not survive realistic turnover costs. All twelve Gold ETF MA configurations were also negative after costs despite positive gross returns. The highest-frequency settings paid the most estimated costs. None of the new hypotheses is supported for live use by this screen. Once the decision-tree strategy depleted its account, Sharpe was no longer meaningful.

The 2024 result file contains per-setting returns, drawdowns, Sharpe ratios, fills, thresholds and cost estimates at `data/derived/gold_stock_intraday_screen.json`. The net figures use ₹1,000,000 initial capital, split equally across the five stock names for equity strategies. Returns compound daily; intraday signals each use their allocated fixed notional. Costs include the project fee router plus stated slippage.

## References to local implementation

`src/eulerlab/intraday/research_screen.py` holds the two newly executable screeners and their fixed rule settings. The generated output is `data/derived/gold_stock_intraday_screen.json`. The candidate cards H-0009 and H-0010 record the two new hypotheses and their red flags. Both screeners are registered in the strategy research library; their results are imported with `make library-sync`.
