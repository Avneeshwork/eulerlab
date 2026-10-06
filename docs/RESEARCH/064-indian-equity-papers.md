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

| Strategy (paper) | Paper reported | Sharpe | Total return | Max drawdown | Fills |
|---|---|---|---|---|---|
| Agarwalla, Jacob & Varma (2013), momentum 12-1 | WML ~21%/yr long-short | 0.87 | +474% | -45% | 10,199 |
| Kundlia & Verma (2021), Amihud illiquidity | ~23%/yr premium | 0.82 | +585% | -68% | 491 |
| Joshipura & Peswani (2017), low 36-month volatility | large caps +8.3%/yr excess | 0.83 | +188% | -33% | 5,236 |
| Agarwalla et al. (2014), betting against beta | BAB 1.70%/month | 0.73 | +142% | -31% | 9,145 |
| Pandey & Samanta (2016), high 60-month volatility | P5 3.77%/month | 0.60 | +214% | -53% | 3,528 |
| Sehgal et al. (2024), low MAX(L5) | 1.33%/month low-minus-high | 0.40 | +84% | -57% | 5,855 |
| Sen (2022), Bharat Forge / Ashok Leyland pair | 17.6% in 2021 | 0.91 | +1074% | -34% | 89 |
| Maher & Parikh (2013), turn of month | effect exists (abstract) | 0.25 | +15% | -17% | 258 |
| Singh & Shaik (2020), expiry day | no significant effect | -0.72 | -23% | -25% | 260 |
| Lu & Patel (2016), day after a holiday | +0.25%/day, 2008-12 only | -0.84 | -34% | -35% | 280 |
| Muruganandan (2020), MACD buy signal | buys -0.13%/day (n.s.) | -0.92 | -37% | -38% | 467 |
| Srinivasan & Kalaivani (2013), Monday and Wednesday | +0.15-0.18%/day | -1.77 | -85% | -85% | 2,054 |

Strategies needing 5 years of history (BAB) or 60 months (high volatility)
start trading in 2020 on a panel that begins in 2015.

## Findings

1. **Nothing here clears the noise bar.** The best Sharpe is 0.91 (the pair)
   against a bar of 2.99. Every number above is one screening run with no
   trial recorded, so none is evidence of an edge.
2. **Against NIFTYBEES held (+221%), three cross-sectional strategies did
   better and three did worse; every index-timing rule did worse.** Momentum,
   illiquidity and high volatility beat it at deeper drawdowns; low volatility,
   low beta and low MAX did not. Turn of the month made +15% while sitting out
   most days; expiry, post-holiday, MACD and Monday/Wednesday lost money after
   costs, the twice-weekly round trips losing 85%.
   The pair's +1,074% is one pair the paper chose with knowledge of 2021, and
   two concentrated cyclical stocks; it is not evidence that pairs work.
3. **The first pass was wrong, and the cause is platform-wide.** Run on the
   named `nifty250`, the illiquid decile made +4,204% and momentum +1,098%.
   `nifty250` is today's most-traded list applied to every past date, so it
   hands a 2016 backtest the stocks that later became liquid — mostly the ones
   that rose. Point-in-time, the same strategies make +585% and +474%.
   HISTORY #16; T-3984.
4. **Two papers' conclusions survive in direction only.** Pandey & Samanta's
   "high volatility wins" and the low-risk papers' "low volatility wins" both
   made money here, because 2020-2026 was a broad rally; neither is a
   comparison of the two.

## Confidence

Medium. Rules follow the papers as read; the adaptations (long only, equal
weight, our universe, NIFTYBEES for indices, close-to-close fills) are stated
per paper. One window, one run each.

## Open questions

- The seven momentum papers, then the eight strategies they specify.
- A point-in-time universe for every named universe on the platform (T-3984).
