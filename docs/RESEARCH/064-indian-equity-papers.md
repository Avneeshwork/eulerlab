# 064 — Twenty papers on Indian equities, and what twelve of them do here

**Question.** The operator asked for 20 research papers on the Indian equity
market, each added to the research library and backtested.

**Sources, fetched 2026-10-06.** Each paper's file in `research/papers/`
records the URL read and whether the full text or only the abstract was
reached. SSRN, ResearchGate, ScienceDirect and Springer refuse automated
fetching; working-paper and repository copies were used where they exist
(IIMA faculty pages, EconStor, MPRA, arXiv, journal PDFs).

| Read in full | Abstract only | Not readable |
|---|---|---|
| Agarwalla et al. 2014 (BAB); Pandey & Samanta 2016; Sehgal et al. 2024; Kundlia & Verma 2021; Agarwalla, Jacob & Varma 2013; Joshipura & Peswani 2017; Srinivasan & Kalaivani 2013; Singh & Shaik 2020; Sen 2022; Muruganandan 2020; Lu & Patel 2016 | Maher & Parikh 2013 (turn of month) | "Hedging Demand and Intraday Momentum within the Indian Stock Market" (2024) |

The seven momentum papers (Maheshwari & Dhankar; Vijaykumar x2; Raju 2023;
Sapate; Aziz & Ansari; "Momentum, reversals and liquidity", PBFJ 2023) were
still being read when the operator asked to push what was done. **They are
not in the library yet.** T-3986.

## Method

`make india-papers` (`src/eulerlab/research/run_india.py`): each strategy in
`backtest/india_papers.py` through `/api/run/batch`, 2016-01-01 to
2026-09-30, Tier B, Indian costs, default workspace. Cross-sectional
strategies choose the 250 most-traded stocks **at each decision date** from
the whole panel; calendar strategies trade NIFTYBEES. Long only and
equal-weighted throughout (see each paper's red flags). Screening runs: none
is in the trial ledger.

NIFTYBEES bought and held over the window: +221% before costs.

## Results

Every strategy below ran 2016-01-01 to 2026-09-30, Tier B, after Indian costs, long only. NIFTYBEES bought and held over the same window: +221% before costs. Sorted by Sharpe; the noise bar is 2.99, and none is in the trial ledger.

| Strategy | Paper | Sharpe | Total return | Max drawdown | Fills |
|---|---|---|---|---|---|
| Volatility-adjusted momentum, top 30 | Vijaykumar (2020) | 1.03 | +813% | -44% | 4601 |
| Nifty above its 60-day average | Mitra (2011) | 0.98 | +155% | -18% | 138 |
| Physical momentum, return over volatility | Tripurana (2023) | 0.93 | +769% | -49% | 1071 |
| Illiquid winners | Aziz (2014) | 0.92 | +650% | -47% | 6035 |
| Pair: Bharat Forge / Ashok Leyland | Sen (2022) | 0.91 | +1,074% | -34% | 89 |
| Risk-managed time-series momentum | Singh (2022) | 0.89 | +321% | -35% | 18659 |
| 12-month momentum, no skip, top 30 | Vijaykumar (2026) | 0.88 | +640% | -55% | 4590 |
| Momentum winners, 12-1, top 30% | Agarwalla (2013) | 0.87 | +474% | -45% | 10199 |
| Time-series momentum, long leg | Singh (2020) | 0.83 | +314% | -43% | 18826 |
| Lowest 36-month volatility quintile | Joshipura (2017) | 0.83 | +188% | -33% | 5236 |
| Most illiquid decile, Amihud | Kundlia (2021) | 0.82 | +585% | -68% | 491 |
| Nearest the 52-week high, top decile | Raju (2023) | 0.74 | +248% | -32% | 4961 |
| Betting against beta, long leg | Agarwalla (2014) | 0.74 | +141% | -30% | 9256 |
| Momentum 3-month formation, 6-month hold | Maheshwari (2015) | 0.71 | +361% | -58% | 1025 |
| Liquid winners | Chui (2023) | 0.69 | +290% | -52% | 5719 |
| High 60-month volatility quintile | Pandey (2016) | 0.60 | +214% | -53% | 3528 |
| Low lottery score, MAX(L5) | Sehgal (2024) | 0.40 | +84% | -57% | 5855 |
| Union Budget days, Nifty | Srinivasu (2025) | 0.39 | +11% | -6% | 26 |
| December only, Nifty | Sah (2009) | 0.38 | +14% | -6% | 20 |
| Mid caps follow large caps, weekly | Sahoo (2022) | 0.32 | +10% | -13% | 86 |
| Turn of the month, Nifty | Maher (2013) | 0.25 | +15% | -17% | 258 |
| Weekly momentum, top decile | Sapate (2017) | 0.18 | +18% | -65% | 24495 |
| Three-year losers | Joshipura (2009) | 0.13 | +5% | -81% | 304 |
| Buy after a 20% monthly fall | Parthasarathy (2022) | -0.07 | -41% | -83% | 745 |
| Monthly expiry day, Nifty | Singh (2020) | -0.72 | -23% | -25% | 260 |
| Day after a holiday, Nifty | Lu (2016) | -0.84 | -34% | -35% | 280 |
| MACD buy signal, Nifty | Muruganandan (2020) | -0.96 | -48% | -48% | 493 |
| Monday and Wednesday, Nifty | Srinivasan (2013) | -1.77 | -85% | -85% | 2054 |
| Bollinger and RSI reversion | Shalinigayathri (2024) | — | — | — | the run passed 900s and was abandoned. T |

## Papers in the library without a backtest

- **Bajpai (2021)**, Application of deep reinforcement learning for Indian stock trading automation. Not backtested.
- **Gavhale (2025)**, F&O Expiry vs. First-Day SIPs: A 22-Year Analysis of Timing Advantages in India's Nifty 50. Not an engine backtest: a savings plan, not a strategy. Tools -> SIP Backtester can compare days of the month.
- **Unknown authors (2024)**, Hedging Demand and Intraday Momentum within the Indian Stock Market. Not backtested here until the paper itself is read.
- **Knuteson (2020)**, Strikingly Suspicious Overnight and Intraday Returns. Not backtested yet: the daily engine fills on closes only; this needs the intraday engine on NIFTYBEES's open and close.
- **Manoharan (2019)**, Candlestick Technical Analysis on Select Indian Stocks: Pattern detection and Efficiency Statistics. Not backtested: the panel records open, high and low only from August 2026, so candle shapes cannot be read over history.
- **Mukherjee (2025)**, Price Action Meets Volatility: A Dual-Factor Strategy for Nifty Gap Forecasting. Not backtested: the trade is close-to-open (the daily engine trades at closes) and India VIX history is not in the data.
- **Ramraj (2025)**, Predicting Stock Prices using Permutation Decision Trees and Strategic Trailing. Not backtested: the model and its parameters are not specified enough to rebuild.
- **Ranse (2026)**, Survivorship Bias in Emerging Market Small-Cap Indices: Evidence from India's NIFTY Smallcap 250. No strategy. See HISTORY #16 and T-3984.
- **Sharma (2025)**, Optimizing Sector Index Rotation and Rebalancing Frequency with Data Mining: A Case Study on Indian National Stock Exchange. Not backtested here: the panel has no sectoral index history.
- **Wang (2025)**, Optimizing Intraday Breakout Strategies on the NSE: A Block-Based Performance Evaluation. Linked: orb_breakout_in, this platform's NSE opening-range breakout, is the nearest coded strategy; its rules are Mesfin's, not this paper's.

## Findings

1. **Nothing clears the noise bar.** The best Sharpe is about 1.0 against a bar of 2.99. Every number here is one screening run with no trial recorded.
2. **Momentum, in its many forms, is the strongest family.** Volatility-adjusted, physical, 12-month, illiquid-winner and time-series momentum all made 300-800% against the index's +221%, at drawdowns of 35-55%. They are largely the same bet: seven momentum definitions here hold overlapping stocks, which the Vijaykumar (2026) paper itself warns about.
3. **The one index-timing rule that worked is the 60-day moving average** (Sharpe 0.98, +155%, drawdown -18% against the index's -38%). The calendar rules mostly lose after costs; Budget days, December and turn of the month make 11-15% over ten years while sitting out most days.
4. **Two data faults made the first passes wrong, and both are platform-wide.** Named universes are today's list applied to the past (HISTORY #16): on `nifty250` the illiquid decile showed +4,204%, point-in-time +585%. NIFTYBEES's 2019 1:10 split had no adjustment (HISTORY #17): the 60-day rule showed -73% before the fix and +155% after.
5. **Most papers could not be read in full.** SSRN, ResearchGate and ScienceDirect block automated reading; the seven momentum papers and several others are built from abstracts, and each paper's red flags say which rules were assumed.

## Confidence

Medium. Rules follow the papers as read; the adaptations (long only, equal weight, a point-in-time top 250, NIFTYBEES for indices, close-to-close fills) are stated per paper. One window, one run each.
