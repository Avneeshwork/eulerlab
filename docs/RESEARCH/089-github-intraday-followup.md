# GitHub intraday strategy follow-up

**Screen date:** 2026-10-15. **Question:** find additional minute-level rules in public repositories, remove duplicates, and test what local NSE data can support.

## Finding

One repository supplied a sufficiently concrete, non-duplicate price rule: pullbacks into EMA-20, confirmed by MACD histogram, with a setup-swing stop and a 1R target. Its author describes this for MES futures, not Indian stocks. We translated the stated mechanics into a fixed NSE stock screen and tested it independently. That is a candidate evaluation, not evidence that the repository's reported performance transfers to India.

## New tested rule

The [source repository](https://github.com/spagnola-analytics/intraday-strategies) describes its `ema_macd_sr` setup as an EMA-20 pullback with MACD histogram confirmation, stop at the setup swing, and take-profit at 1R. The repository also says its data are Polygon 1-minute MES/ES futures bars. The fetched README does not publish an NSE result. Fetch date: 2026-10-15.

For this frozen NSE screen, a long requires the prior close above session EMA-20, a completed minute low touching EMA-20 and close reclaiming it, and positive MACD(12,26,9) histogram. The short is mirrored. Entry is the next traded minute open. Stop is the extreme of the signal bar and four preceding bars; target is 1R. A stop wider than 1% of entry is skipped. We allow one trade per symbol/session. Same-bar stop and target resolves to stop; a gap through the stop fills at that bar's open. Every position closes by 15:10.

## Data and execution

Input is the local Kite NSE one-minute archive for HDFCBANK, ICICIBANK, TCS and INFY. The fixed evaluation window is 2024-01-01 through 2024-11-30, the same cutoff and four-name universe used in research 088. The loader excludes any parquet file whose named end date crosses 2024-11-30. No data after the cutoff is read. Each stock uses ₹250,000 notional; execution pays date-aware NSE intraday charges and an assumed 2 bp slippage per side. These costs are estimates; actual contract-note calibration and market impact are absent (A-016, T-906, T-907).

Run `make github-followup-intraday` to reproduce the run and write `data/derived/github_followup_stock_strategies.json`. Run `make library-sync` to attach the measured result to the registered Strategy Library card. The second card records the overnight fade as blocked; it does not import or display a synthetic result.

### Local result

| Candidate | Gross return | Net return | Net Sharpe | Trades | Estimated charges + slippage |
|---|---:|---:|---:|---:|---:|
| EMA-20/MACD pullback, 1R | -0.26% | **-19.17%** | -16.704 | 896 | ₹210,107 |

This did not work on the selected four-stock sample. It traded almost once per stock on every common evaluation session; estimated costs overwhelmed the gross result. It is rejected as a profitable candidate for this setup and window. Do not tune this same candidate and resubmit it as an independent discovery. The ongoing search may test distinct sourced hypotheses.

## Additional repository triage

| Repository | Candidate found | Decision |
|---|---|---|
| [spagnola-analytics/intraday-strategies](https://github.com/spagnola-analytics/intraday-strategies) | EMA-20/MACD pullback; overnight high/low fade; FVG gap; order-block bounce; VWAP mean reversion; ORB pullback | Test the EMA/MACD setup. Overnight levels require futures overnight data, FVG/gap and ORB/VWAP families duplicate existing work, and the README does not define a deterministic market-structure rule. |
| [ezhilengels/zerodhaAutoIntraBot](https://github.com/ezhilengels/zerodhaAutoIntraBot) | Gap-up quiet-volume VWAP pullback, several VWAP reclaim variants, ORB, pivots and EMA crossover | Exclude as duplicate gap/VWAP/ORB/EMA families; its code path is for signal automation, not independent profitability evidence. |
| [notvikke/NSE_Trade_Simulation](https://github.com/notvikke/NSE_Trade_Simulation) | Extreme RSI mean reversion with discretionary AI confirmation | Exclude as duplicate extreme-reversal work; the AI veto is not a fixed reproducible signal. |
| [HeneelParmar/Algorithmic-Trading-Strategy-Backtester](https://github.com/HeneelParmar/Algorithmic-Trading-Strategy-Backtester) | Moving-average crossover and RSI mean reversion | Exclude from minute research: README's stated sample is daily index data; both broad families are already represented. |
| [CuriousObservator/Systematic-Intraday-Mean-reversion-Strategy](https://github.com/CuriousObservator/Systematic-Intraday-Mean-reversion-Strategy) | Open-to-close cross-sectional gap reversal | Exclude from minute entries: the signal is known at the open and held to close, overlapping existing gap-reversal research. README also omits exact trigger thresholds. |
| [builditwithgk/dhan-nifty-algo-trading-lab](https://github.com/builditwithgk/dhan-nifty-algo-trading-lab) | ORB, momentum, VWAP mean reversion and index options | Exclude as duplicate families. The repository reports that its tested textbook equity setups failed its gate; its cost and OOS methodology is a useful review reference. |
| [vijaxx/algo-trading-system](https://github.com/vijaxx/algo-trading-system) | ORB, EMA/RSI, VWAP reversion, Supertrend and Bollinger breakout | Exclude as duplicates of existing ORB, VWAP, EMA/momentum and squeeze work. |
| [om-gorakhia/nse-algo-trading-system](https://github.com/om-gorakhia/nse-algo-trading-system) | Initial-balance failure and multiple stock patterns | Initial-balance failure has already been screened in research 088; do not repeat it under another repository. |
| [Gaurav-UwU/intraday-playbook](https://github.com/Gaurav-UwU/intraday-playbook) | ORB, VWAP mean reversion and gap-go with retail cost assumptions | Exclude as duplicates. Its claims need an independent test and should not be treated as an edge. |
| [voletiramu/nse-fno-1min-data](https://github.com/voletiramu/nse-fno-1min-data) | 214-symbol NSE 1-minute data set, with strategy references | Data source candidate only. Its README does not provide a new, fully specified and independently reproducible strategy rule. Do not copy or redistribute its data without checking its terms. |

These are GitHub README/code descriptions, not peer-reviewed evidence. Repository popularity, author-reported backtests, and strategy names are not profitability proofs. Research 088 contains the previous batch and its eight negative local results.

## Limitations and next data

The local screen is only four fixed stocks and one evaluation period, so it does not establish broad cross-sectional robustness. Intrabar OHLC cannot identify the true ordering of all trades; resolving stop/target collisions as stop-first is conservative but still does not model queue position, spread, partial fills or market impact. The source repository has one commit and no visible track record of external replication.

The source's overnight-high/low fade remains blocked for NSE cash until historical executable pre-open or overnight prices and credible auction fills are available. We did not substitute the previous cash-session high/low because that changes the rule's defining level.

## Sources

- [spagnola-analytics strategy repository](https://github.com/spagnola-analytics/intraday-strategies) — fetched 2026-10-15.
- [Zerodha bot repository](https://github.com/ezhilengels/zerodhaAutoIntraBot) — fetched 2026-10-15.
- [NSE simulation repository](https://github.com/notvikke/NSE_Trade_Simulation) — fetched 2026-10-15.
- [Daily NIFTY strategy backtester](https://github.com/HeneelParmar/Algorithmic-Trading-Strategy-Backtester) — fetched 2026-10-15.
- [Indian open-to-close mean-reversion repository](https://github.com/CuriousObservator/Systematic-Intraday-Mean-reversion-Strategy) — fetched 2026-10-15.
- [Dhan intraday research lab](https://github.com/builditwithgk/dhan-nifty-algo-trading-lab) — fetched 2026-10-15.
- [NSE/BSE algo trading system](https://github.com/vijaxx/algo-trading-system) — fetched 2026-10-15.
- [NSE algo trading system](https://github.com/om-gorakhia/nse-algo-trading-system) — fetched 2026-10-15.
- [Intraday playbook](https://github.com/Gaurav-UwU/intraday-playbook) — fetched 2026-10-15.
- [NSE F&O minute data repository](https://github.com/voletiramu/nse-fno-1min-data) — fetched 2026-10-15.
