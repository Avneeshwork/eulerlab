# 103 — Cost-aware machine-learning intraday signals on NSE stocks

**Date:** 2026-10-15 · **Status:** backtested; failed after realistic modeled costs

## Source and hypothesis

Gaona, Rangel-Madariaga and Uribe (2026) compare Decision Tree, Random Forest and XGBoost signals over 1–30 minute horizons using one-minute data, transaction-cost-aware labels, rolling out-of-sample evaluation, and Bayesian model selection. Their result varies by asset; 30 minutes is often selected, while only a subset of their U.S. equities, FX pairs and crypto assets remain positive after the study's cost assumptions. This motivates a fixed NSE adaptation, not a claim that the published U.S. result transfers to India.

The local screen freezes one Random Forest, one 30-minute horizon, and five current liquid NSE stocks. Indicators use completed bars: 10-period SMA/EMA, session VWAP, MACD(12,26,9), stochastic(14,3), one-bar momentum and ROC, Bollinger(20,2), and RSI(14). The model trains once on 2022–2023. For each signal at minute *t*, it enters at the next traded minute's open and exits at the open 30 minutes after entry. It does not overlap positions in a stock or hold across sessions.

The label is long or short only if that realized training move clears date-aware two-sided NSE charges plus assumed 2 bp slippage per side; otherwise it is flat. The fee threshold uses the fee side sequence corresponding to the target direction. The 2024-01-01 to 2024-11-30 evaluation is fixed development data, **not** an untouched future holdout.

## Results

| Measure | Result |
|---|---:|
| Universe | RELIANCE, HDFCBANK, ICICIBANK, INFY, TCS |
| Evaluation | 224 sessions, through 2024-11-30 |
| Starting capital | ₹10,00,000; five ₹2,00,000 starting sleeves |
| Round trips / fills | 9,866 / 19,732 |
| Gross P&L | ₹89,016 on the dynamically sized trades |
| Modeled fees and slippage | ₹9,94,693 |
| Ending equity | ₹94,323 from ₹10,00,000 starting capital |
| Net portfolio return | **−90.57%** |
| Net Sharpe / max drawdown | **−34.087 / −90.57%** |

The cost-aware target does not translate into profitable predictions at executable prices. Across 9,866 round trips (about 44 per evaluation session), gross P&L was about ₹9.02 per trade on average while realized modeled charges and assumed slippage averaged about ₹100.82 per trade. The five isolated sleeves were each sized from live sleeve equity, charges were recalculated using the actual integer quantity, and a sleeve stopped if its equity reached zero. This candidate fails the profitability objective. No threshold, model or trade filter was tuned against the evaluation results.

## Limitations

- The published paper uses 40 non-Indian assets and a fixed U.S.-oriented equity cost assumption; this is an independent Indian adaptation, not a reproduction.
- The archive contains five selected current liquid names, so survivorship and selection bias remain.
- Slippage is assumed at 2 bp per side; actual queue position, spread, market impact, short borrow and availability are not modeled. Those limitations do not rescue the candidate: modeled costs already overwhelm gross P&L.
- Capital is split into five isolated sleeves, re-sized from each sleeve's live equity before each sequential trade. A breached sleeve is floored at zero and stops. No margin liquidation, external cash additions, or cross-sleeve rebalancing is modeled.
- This screen used one fit per stock on 2022–2023 and one 2024 development evaluation. It does not establish future performance.
- No data after 2024-11-30 was opened.

## Reproduction and Research Library

Run `make cost-aware-ml-intraday`; the trade log and portfolio curve are in `data/derived/cost_aware_ml_nse_stock_strategies.json`. Run `make library-sync` to attach the measured curve to the registered strategy card. The paper record marks the local adaptation as backtested and reports the negative net result.

## Source

- Gaona, Rangel-Madariaga & Uribe (2026), [Intraday trading strategy selection under transaction costs with machine learning](https://www.frontiersin.org/journals/applied-mathematics-and-statistics/articles/10.3389/fams.2026.1888767/full), *Frontiers in Applied Mathematics and Statistics*, DOI [10.3389/fams.2026.1888767](https://doi.org/10.3389/fams.2026.1888767).
