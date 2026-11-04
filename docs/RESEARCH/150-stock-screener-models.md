# 150 — Which models should pick Indian stocks for long-term and swing holding, and can they be backtested here?

## Question

The operator, 2026-11-04: build a screener showing which stocks to buy for the long term and for swing trades; research papers on which stocks to hold short and long term; backtest them; use the platform's best existing strategies with the new work. Long term rebalances monthly, swing weekly, with a history of past selections and how they did.

## Sources

- A. Gu, Kelly and Xiu, "Empirical Asset Pricing via Machine Learning", NBER WP 25398 (RFS 2020), https://www.nber.org/papers/w25398, fetched 2026-11-04.
- B. Novy-Marx, "The Other Side of Value: Good Growth and the Gross Profitability Premium", NBER WP 15940 (JFE 2013), https://www.nber.org/papers/w15940, fetched 2026-11-04.
- C. Jacob, Pradeep and Varma, "Performance of Quality Factor in Indian Equity Market", IIMA WP 2022-11-01, https://ideas.repec.org/p/iim/iimawp/14687.html, fetched 2026-11-04.
- D. Asness, Moskowitz and Pedersen, "Value and Momentum Everywhere", JF 68(3) 2013. Search results and abstract summaries only; https://pages.stern.nyu.edu/~lpederse/papers/ValMomEverywhere.pdf not fetched.
- E. George and Hwang, "The 52-Week High and Momentum Investing", JF 59(5) 2004. Search results only.
- F. Piotroski, "Value Investing: The Use of Historical Financial Statement Information...", JAR 2000. SSRN answered 403 and RePEc 404 on 2026-11-04; secondary sources only, which disagree on the return figure (13.4% vs 23% a year).
- G. SEBI LODR Regulation 33 timelines (45 days for quarters, 60 for the year): secondary sources only (taxguru, lexplosion, an NSE-hosted SEBI circular of 2020 extending FY2020 results to 31 July 2020). sebi.gov.in returned 404 for the regulation page tried.
- H. Measured: screener.in snapshots in this project (2,360 companies since 2026-08): annual P&L, balance sheet, cash flow and ratios from FY2015; Tata Steel's FY2022 EPS (32.88) is in units after its July 2022 10-for-1 split, so EPS is back-adjusted for later actions.
- I. This project: 68 stored daily strategies, about three independent bets (HISTORY #44); best by Sharpe 2016-2026: Sharpe momentum (tuned) 1.23, Stocks on the Move 1.05, Weinstein stage 2 1.02, physical momentum 0.93, frog in the pan 0.93 (strategy map).

## Findings

- Price momentum, liquidity and volatility are the strongest predictors in every method; trees and neural nets beat linear ranks by capturing interactions (A).
- Profitability predicts returns about as well as value and strengthens it (B); value and momentum are negatively correlated, so blends are steadier (D).
- In India quality is the strongest factor: QMJ four-factor alpha 0.92% a month; long-only 0.69% (C).
- Nearness to the 52-week high explains most of momentum's profit (E); cheap stocks with improving statements beat cheap stocks deteriorating (F, secondary).
- Everything this project has tested is price-based and mostly one momentum bet (I); accounting signals are what it has not tried.
- Fundamentals can be backtested only with a publication date rule (G, 90 days used), with EPS converted to each date's units (H), and with two biases left: restatement and survivorship (H).

## Decision

ADR-136: six models fixed before testing (H-0030 to H-0035): quality momentum, value-momentum-quality, Piotroski value, a tree ranker (long term, monthly; Piotroski quarterly), trend pullback and 52-week breakout (swing, weekly); with the five best existing strategies on the same page. Screening backtests on the common engine; the gate is the operator's.

## Confidence

Medium for the price models; low to medium for the fundamental ones because of restatement and survivorship.

## Open questions

- Read D, E and F in full; read SEBI's own text of Regulation 33.
- Point-in-time fundamentals with true publication dates (NSE results filings) would remove the 90-day assumption.
