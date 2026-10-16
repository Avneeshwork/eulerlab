# 104 — FII/DII flow: entry, exit, and what the data can tell us

**Date:** 2026-10-15 · **Status:** literature update; no new strategy backtest

## Finding

The added ICRIER study by Batra (2003) is a useful counterweight to treating FII net buying as a bullish trigger. Using aggregate Indian equity flows and market returns from 2000–2002, it reports daily positive-feedback trading: recent market returns help explain FII flows. Its event study does not find persistent subsequent market-price impact after large FII buy or sell imbalances, nor evidence that those imbalances destabilize prices. This points to reverse timing—price movement can lead reported FII activity—rather than a reliable “FII entered, so buy now” rule.

This does not negate later evidence that flow innovations can coincide with stock-level price pressure or that FII selling can raise volatility. The studies use different measures, samples, horizons, and outcomes:

| Evidence | What it measures | Implication for entry/exit |
|---|---|---|
| Batra (2003) | Aggregate daily FII equity purchases and index returns | Daily flow can follow prior returns; large imbalances did not create persistent market moves in this sample. |
| Acharya, Anshuman & Kumar (2013) | Stock-specific daily flow innovations | Abnormal stock-level flows coincide with returns; low-flow names partly reverse over days. It does not yield a public aggregate-flow minute signal. |
| Chhimwal, Bapat & McMillan (2020) | Unexpected aggregate FPI/DII flows and segment volatility | FPI shocks, especially selling, are associated with volatility; DII flows moderate volatility. This is a risk hypothesis, not return direction. |
| NSE participant OI screen (Research 097) | Lagged index-futures positions, not cash trades | The fixed adaptation was gross positive but net negative after modeled fees and slippage. |

## Entry and exit interpretation

1. **Do not use the current day's NSE FII/DII cash totals to trade that same day's intraday bars.** The totals describe the full session and are published after the close. That is lookahead.
2. **A next-session test is possible only if the record's actual release time is known.** Without a timestamped historical archive, placing today's flow on today's date or assuming a fixed evening release time can leak information.
3. **Aggregate flow has no stock identity.** It cannot support “buy the stocks FIIs entered” or stock-specific entries and exits. That requires stock-level institutional transaction data.
4. **Positioning is different from executed flow.** Participant-wise open interest measures outstanding derivative positions by group. It can indicate exposure changes, but not cash-market investment, exact entry time, or whether the position hedges another book.
5. **Potential use is as a risk context:** test whether a lagged, unusually large FII sell imbalance predicts higher next-session realized volatility, and whether prior DII buying moderates it. Evaluate volatility and drawdown first. A directional filter needs separate out-of-sample evidence after costs.

## What is and is not backtested

Research 097's frozen participant-OI direction screen remains the only local FII-linked return backtest. Across five liquid stocks and 224 2024 evaluation sessions, it returned **+20.54% gross and −3.31% net** after the modeled fees and assumed slippage (Sharpe 1.878 gross, −0.271 net). That is a non-profitable proxy test, not a replication of the flow papers and not a test of cash-market FII/DII entry or exit.

I did not create a new strategy or fit a volatility model here: the repository has no point-in-time historical NSE cash FII/DII series with release timestamps. The existing endpoint is latest-day only, as documented in [`004-india-macro-data-sources.md`](004-india-macro-data-sources.md). A credible cash-flow test therefore needs prospective daily capture with `trade_date`, `first_published_at`, `retrieved_at`, source, and revision history. Use the next session only after the first publication timestamp.

## Research Library

Added `batra-2003-fii-trading-strategies-india.yaml` with the source's universe, horizon, results, and data limits. It is deliberately recorded as a paper idea rather than a backtested strategy.

## Source

- Batra, Amita (2003), [FII Trading Strategies](https://icrier.org/pdf/wp109.pdf), ICRIER Working Paper 109. The paper reports daily return-chasing by FIIs, a return-to-flow direction in its Granger tests, and no significant persistent price effect from large daily FII imbalance events. See its empirical analysis and conclusions (pp. 12–24).
- Related local screen and data audit: [`097-fii-dii-entry-exit-impact.md`](097-fii-dii-entry-exit-impact.md) and [`004-india-macro-data-sources.md`](004-india-macro-data-sources.md).
