# Further GitHub intraday strategy validation screen

**Screen date:** 2026-10-15
**Purpose:** Continue the search for five net-profitable intraday strategies, while recording screened sources and rejecting unsupported performance claims.

## Results at a glance

No newly reviewed strategy qualifies as a profitable Indian-stock intraday candidate. The strongest-looking new source was the [Divo15 Bank Nifty system](https://github.com/Divo15/quant-internship-banknifty). Its README reports a full-period return of +39.2%, but also reports an out-of-sample profit factor of 0.83 and a loss of roughly $31,060. The source selects a momentum or mean-reversion mode from a Hurst estimate, then trades a rolling price-deviation z-score with a 200-bar trend filter and volatility-scaled exits. The existing library already contains OU/z-score mean reversion, so this is a close variant rather than an independent new strategy. The source's own OOS result is negative. We therefore did not copy or register it as a new strategy, and did not use the headline full-period result as evidence of an edge.

This is source triage, not a local NSE re-test. Its public README says Bank Nifty minute data, while this workspace's local minute archive is cash-equity data for five fixed stocks. Re-testing the whole signal would add little distinct evidence to the existing OU and momentum screens. A genuinely different hypothesis or suitable index/derivative history is needed before reconsidering it.

## Repository screen

| Repository | What was checked | Disposition |
|---|---|---|
| [Divo15/quant-internship-banknifty](https://github.com/Divo15/quant-internship-banknifty) | Hurst-selected momentum/reversion, z-score entry, SMA(200), adaptive volatility exits; README's own IS/OOS breakdown | **Rejected as duplicate and negative source OOS.** The overall +39.2% headline is outweighed by reported OOS −$31,060 and PF 0.83. Not a local NSE backtest. |
| [solste7en/strategy-research](https://github.com/solste7en/strategy-research) | Six US intraday rule families and walk-forward results | **No new NSE rule selected.** README reports 2025 training results were strong, but its 2026-Q1 walk-forward was −$330 and only 2/12 tickers profitable. The ORB/VWAP/volume-surge families duplicate existing research; the other rules need source-by-source deduplication before testing. |
| [rinturifle/alpha-engine](https://github.com/rinturifle/alpha-engine) | Minute-capable event loop, next-open execution, intrabar risk checks, walk-forward and cost model | **Backtesting infrastructure, not a distinct strategy.** Valuable validation design; no new strategy to test. |
| [akoiralaa/systematic-trading-engine](https://github.com/akoiralaa/systematic-trading-engine) | US intraday trend system with OLS regimes, ATR exits and expanding walk-forward | **Not selected.** The exposed rules are a broad trend/ATR family already represented; the US session and universe do not match NSE cash. |
| [nyyyaomi/intraday-momentum-research](https://github.com/nyyyaomi/intraday-momentum-research) | SPY/QQQ volatility-band momentum, VWAP exits and transaction costs | **No historical edge evidence.** Included demo uses synthetic data and the repository says it lacks out-of-sample or walk-forward validation. Momentum/VWAP overlap existing work. |
| [noterminusgit/statarb](https://github.com/noterminusgit/statarb) | US equity statistical-arbitrage framework with 30-minute bars and many factor families | **Not selected.** Requires point-in-time US universe, risk-model and event data absent here; broad stat-arb/pairs overlap existing research. |
| [Kumamon9999/FactorAlpha](https://github.com/Kumamon9999/FactorAlpha) | A-share five-minute features, portfolio factors and rebalance execution | **Data/method mismatch.** It is a portfolio-factor pipeline for Chinese A-shares, not a fully specified Indian-stock intraday entry/exit strategy. |
| [mahimn01/trading-algo](https://github.com/mahimn01/trading-algo) | Example 5-minute ORB with volume confirmation, stop and target | **Duplicate.** ORB is already represented and this example does not establish an independent profitable result. |
| [repque/intraday](https://github.com/repque/intraday) | Generic event-based initial-breakout examples on IVV/SPY | **Duplicate and insufficient evidence.** Initial breakout overlaps the existing ORB family; sample data and examples do not establish net profitability. |
| [donatov/trading-strategy-backtester](https://github.com/donatov/trading-strategy-backtester) | US ICT-style and trend strategies with configurable data providers | **Not selected.** The project warns results depend on data and assumptions; the surfaced rules are either underspecified for faithful NSE replication or overlap existing trend/gap work. |

The candidates and implementation results from prior GitHub batches remain in [088](088-company-and-github-intraday-strategy-screen.md), [089](089-github-intraday-followup.md), and [090](090-github-surge-pullback-breakout.md). Across those notes, tested local adaptations were negative or too sparse to support a profitability claim. This screen does not change that count.

## Follow-up rules

- Do not tune the Bank Nifty parameters against the 2024 evaluation period to chase a positive result.
- Revisit the Hurst selector only as a pre-registered incremental test against the existing fixed OU and momentum baselines, using a suitable index/futures dataset and an untouched evaluation window.
- Continue screening for rules with a deterministic signal, source-reported OOS evidence, and input fields present in the local NSE archive. Add rejected, tested and data-blocked findings to the Research Library so candidates are not rediscovered as if new.
- A strategy counts toward the five only after a sufficiently sampled, realistic, net-of-cost out-of-sample test is positive. One positive trade or a source README headline is not enough.
