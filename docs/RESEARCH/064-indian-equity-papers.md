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
added afterwards from their abstracts (T-3986), and nineteen more in a second
batch (T-3992). On 2026-10-07 the data in research 065 unlocked five of the
papers that had no backtest; two run through the engine (in the table below)
and three are calculations (the section after it).

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
| Nifty above its 60-day average ¹ | Mitra (2011) | 1.12 | +192% | -17% | 138 |
| Volatility-adjusted momentum, top 30 | Vijaykumar (2020) | 1.03 | +813% | -44% | 4601 |
| Physical momentum, return over volatility | Tripurana (2023) | 0.93 | +769% | -49% | 1071 |
| Illiquid winners | Aziz (2014) | 0.92 | +650% | -47% | 6035 |
| Pair: Bharat Forge / Ashok Leyland | Sen (2022) | 0.91 | +1,074% | -34% | 89 |
| Risk-managed time-series momentum | Singh (2022) | 0.89 | +321% | -35% | 18659 |
| 12-month momentum, no skip, top 30 | Vijaykumar (2026) | 0.88 | +640% | -55% | 4590 |
| Momentum winners, 12-1, top 30% | Agarwalla (2013) | 0.87 | +474% | -45% | 10199 |
| Sector rotation, middle five, yearly ² | Sharma (2025) | 0.84 | +256% | -37% | 59 |
| Time-series momentum, long leg | Singh (2020) | 0.83 | +314% | -43% | 18826 |
| Lowest 36-month volatility quintile | Joshipura (2017) | 0.83 | +188% | -33% | 5236 |
| Most illiquid decile, Amihud | Kundlia (2021) | 0.82 | +585% | -68% | 491 |
| Nearest the 52-week high, top decile | Raju (2023) | 0.74 | +248% | -32% | 4961 |
| Betting against beta, long leg | Agarwalla (2014) | 0.74 | +141% | -30% | 9256 |
| Momentum 3-month formation, 6-month hold | Maheshwari (2015) | 0.71 | +361% | -58% | 1025 |
| Liquid winners | Chui (2023) | 0.69 | +290% | -52% | 5719 |
| Turn of the month, Nifty ¹ | Maher (2013) | 0.65 | +49% | -13% | 258 |
| High 60-month volatility quintile | Pandey (2016) | 0.60 | +214% | -53% | 3528 |
| Mid caps follow large caps, weekly ¹ | Sahoo (2022) | 0.56 | +20% | -11% | 86 |
| Union Budget days, Nifty ¹ | Srinivasu (2025) | 0.48 | +14% | -6% | 26 |
| December only, Nifty ¹ | Sah (2009) | 0.44 | +16% | -6% | 20 |
| Low lottery score, MAX(L5) | Sehgal (2024) | 0.40 | +84% | -57% | 5855 |
| Monday and Wednesday, Nifty ¹ | Srinivasan (2013) | 0.23 | +20% | -30% | 2054 |
| Bollinger and RSI reversion ² | Shalinigayathri (2024) | 0.19 | +19% | -72% | 943 |
| Weekly momentum, top decile | Sapate (2017) | 0.18 | +18% | -65% | 24495 |
| Three-year losers | Joshipura (2009) | 0.13 | +5% | -81% | 304 |
| Monthly expiry day, Nifty ¹ | Singh (2020) | 0.05 | +1% | -12% | 258 |
| Buy after a 20% monthly fall | Parthasarathy (2022) | -0.07 | -41% | -83% | 745 |
| MACD buy signal, Nifty ¹ | Muruganandan (2020) | -0.21 | -14% | -23% | 493 |
| Day after a holiday, Nifty ¹ | Lu (2016) | -0.27 | -13% | -17% | 280 |
| Bullish candles, held 5 days ² | Manoharan (2019) | -0.34 | -56% | -63% | 22285 |

¹ Re-run 2026-10-07 after the cost model stopped charging ETF units the share
STT (HISTORY #18). Before the fix: Monday/Wednesday -85%, turn of the month
+15%, the 60-day average +155% (Sharpe 0.98), expiry day -23%, MACD -48%,
post-holiday -34%, Budget days +11%, December +14%, mid caps follow large caps
+10%. The expiry-day run also reads the confirmed expiry dates (research 065).

² Run 2026-10-07: Bollinger + RSI finished under the four-hour limit; sector
rotation and candles were unlocked by the data in research 065.

## Calculations the engines cannot run (2026-10-07)

`make session-studies` (`src/eulerlab/research/session_studies.py`), same
window. Not engine runs: no fills, no result store, no trial. The overnight
trades use Nifty futures, one contract per leg, never across a roll, with the
futures cost model on every round trip; NIFTYBEES's opens are first prints up
to 20% from its value and cannot be traded on (research 066). Futures returns
here are excess returns: the cash behind the position would also earn
interest, which is left out.

**Knuteson (2020), overnight vs intraday.**

| Measure | Overnight | Intraday |
|---|---|---|
| Nifty 50 index, gross (the paper's measure) | +1,568%, Sharpe 2.66 | -83%, Sharpe -1.22 |
| Nifty future, gross | +64%, Sharpe 0.52 | +6%, Sharpe 0.11 |
| Nifty future, after costs (2,652 round trips) | -19%, Sharpe -0.15 | -47%, Sharpe -0.40 |

The paper's pattern is reproduced on the index and almost vanishes on a
tradable instrument. The index's open is built from its constituents' first
prints and its close from a 30-minute average, which leans every measured
overnight "gap" upward; the future's open and close are both trades. The
future still earns more overnight than intraday, but not enough to pay for a
round trip every day. The index held over the window: +184% gross.

**Mukherjee (2025), calm rising days gap up.**

| | Next open gapped the predicted way | On any day |
|---|---|---|
| Index: green day, VIX down → gap up | 70.7% (579 of 819) | 66.8% |
| Index: red day, VIX up → gap down | 37.3% (298 of 800) | 33.2% |
| Future: green day, VIX down → gap up | 60.3% (494 of 819) | 56.8% |
| Future: red day, VIX up → gap down | 46.9% (375 of 800) | 43.2% |

The paper's 69.6% is reproduced (70.7%) but is mostly the base rate: on the
index, any day gaps up 66.8% of the time. The signal adds three to four points
on both measures. Trading it, long the future from a signal close to the next
open: +56% gross, **+25% after costs, Sharpe 0.42, max drawdown -11%**, in the
market 819 nights out of 2,652.

**Gavhale (2025), expiry-day vs first-day SIP.** ₹10,000 a month into the
Nifty 50 at the close, valued at 2026-09-30, using the confirmed expiries:

| Window | First trading day | Expiry day |
|---|---|---|
| 1 year | -13.7% XIRR | -14.2% |
| 3 years | -2.3% | -2.5% |
| 5 years | 3.37% | 3.48% |
| 10 years | 8.86% | 8.88% |
| 2016-2026 | 9.14% | 9.18% |

The paper's 0.5-2.5% a year advantage for expiry-day SIPs over one to five
years is not reproduced: the two days are within half a point at every
horizon, and the first day was ahead over one and three years.

## Papers in the library without a backtest

- **Bajpai (2021)**, deep reinforcement learning for Indian stock trading. The agent and its training are not specified enough to rebuild.
- **Ramraj (2025)**, permutation decision trees with trailing stops. The model and its parameters are not specified enough to rebuild.
- **Unknown authors (2024)**, hedging demand and intraday momentum. The paper itself was never readable; its template needs minute data over years.
- **Ranse (2026)**, survivorship bias in the Nifty Smallcap 250. No strategy; see HISTORY #16 and T-3984.
- **Wang (2025)**, intraday breakouts on the NSE. Linked to `orb_breakout_in`, whose rules are Mesfin's, not this paper's.

## Findings

1. **Nothing clears the noise bar.** The best Sharpe is 1.12 against a bar of 2.99. Every number here is one screening run with no trial recorded.
2. **Momentum, in its many forms, is the strongest family.** Volatility-adjusted, physical, 12-month, illiquid-winner and time-series momentum all made 300-800% against the index's +221%, at drawdowns of 35-55%. They are largely the same bet: seven momentum definitions here hold overlapping stocks, which the Vijaykumar (2026) paper itself warns about.
3. **The one index-timing rule that clearly worked is the 60-day moving average** (Sharpe 1.12, +192%, drawdown -17% against the index's -38%), the best result here. With ETFs charged their real tax (HISTORY #18) the calendar rules mostly make a little: turn of the month +49%, Monday/Wednesday +20%, Budget days and December 14-16% while sitting out most days; MACD, post-holiday and expiry day still do not.
4. **Three platform-wide faults made earlier passes wrong.** Named universes are today's list applied to the past (HISTORY #16): on `nifty250` the illiquid decile showed +4,204%, point-in-time +585%. NIFTYBEES's 2019 1:10 split had no adjustment (HISTORY #17): the 60-day rule showed -73% before the fix and +155% after. ETF units were charged a share's STT (HISTORY #18): Monday/Wednesday showed -85%, and +20% after the fix.
5. **Most papers could not be read in full.** SSRN, ResearchGate and ScienceDirect block automated reading; the seven momentum papers and several others are built from abstracts, and each paper's red flags say which rules were assumed.
6. **Sector rotation's middle five works here too** (Sharpe 0.84, +256% after costs against NIFTYBEES's +221% before), on index levels, which cannot be bought directly.
7. **Candles lose to costs.** Three bullish patterns on the 50 most-traded stocks, held five days, paid ₹7 lakh of costs on ₹10 lakh and lost 56%.
8. **The overnight effect is mostly how the index is measured.** On the Nifty 50 index, holding overnight made +1,568% and intraday lost 83%, as the paper found. On the Nifty future, whose open and close are both trades, overnight made +64% and intraday +6%, and both lose after a round trip a day. The VIX gap signal's 70% accuracy is mostly the base rate; traded on the future it made +25% after costs.

## Confidence

Medium. Rules follow the papers as read; the adaptations (long only, equal weight, a point-in-time top 250, NIFTYBEES for indices, close-to-close fills) are stated per paper. One window, one run each.
