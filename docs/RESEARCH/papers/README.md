# Papers

The primary sources behind the strategies in `src/eulerlab/intraday/papers.py`.
Kept here so a claim can be checked against the paper rather than against a
summary of it — which matters most for the papers that are *not* here.

Run `./fetch.sh` to populate this folder. The PDFs are not committed — arXiv is
a permanent archive, so retrievability is the property worth keeping, not a
megabyte of binary in git history.

| File | Paper | Coded as |
|---|---|---|
| `mesfin-2026-arxiv-2605.04004-intraday-falsification.pdf` | Mesfin, M. (2026). *Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures: A Systematic Falsification Study.* arXiv:2605.04004 | 9 of the 10 signals — `orb_breakout`, `range_expansion`, `liquidity_grab`, `gap_fill_fade`, `gap_continuation`, `volume_spike`, `volume_dryup`, `volatility_regime`, `ou_reversion` |
| `gao-2015-intraday-momentum-first-half-hour.pdf` | Gao, Han, Li & Zhou. *Intraday Momentum: The First Half-Hour Return Predicts the Last Half-Hour Return.* Working paper, December 2015 (JFE 2018 as *Market Intraday Momentum*). A third-party copy; SSRN 2440866 | `session_papers.gao_timing` (research 071) |
| `zarattini-2025-beat-the-market-spy.pdf` | Zarattini, Aziz & Barbon. *Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY).* SFI paper 24-97, version 3 February 2025, from the University of St. Gallen repository. Listed here until 2026-10-11 as not retrievable; SSRN still returns 403, the university does not | `session_papers.noise_area` (research 071) |
| `tripathi-aggarwal-2015-prior-return-intraday.pdf` | Tripathi & Aggarwal. *Prior Return Effect in Indian Stock Market: An Intra-day Analysis.* International Journal of Financial Management 5(1), January 2015, from the publisher's site. Data is 2010 | `india_papers.extreme_reversal_signals` (research 076) |
| `memon-2026-closing-auction-session.pdf` | Memon, Anklesaria-Dalal, Vidhani & Borkar. *Price Discovery or Price Pressure? High-Frequency Evidence from India's New Closing Auction Session.* IJLRP 7(10), October 2026, from the journal's site | Not coded: the effect is from the auction to the next open, which is overnight. Research 076 records it as the strongest lead found |

## Not here, and why that matters

| Paper | Status |
|---|---|
| Zarattini, Barbon & Aziz (2024), *A Profitable Day Trading Strategy For The U.S. Equity Market*, SSRN 4729284 | **Not retrievable.** SSRN returns 403 to automated fetching. `orb_in_play` is coded from the publisher's own summary and an independent third-party reproduction, which agree on every number used. Treat any result as testing *our reading* of the rule until the paper is obtained |
| Maróy (2025), *Improvements to Intraday Momentum Strategies*, SSRN 5095349 | Not retrievable, not coded |
| Wang & Gangwar (2025), *Optimizing Intraday Breakout Strategies on the NSE: A Block-Based Performance Evaluation*, SSRN 5198458 | **Not retrievable** (403). `india_papers.orb_volume_trade` is coded from the abstract, which gives the range lengths, volume thresholds and holding periods but not what a volume surge is measured against (A-058) |
| *Hedging Demand and Intraday Momentum within the Indian Stock Market* (2024), ResearchGate 383567351 | **Not retrievable** (403); authors not confirmed. `india_papers.rest_of_day` follows Baltussen, Da, Lammers & Martens (JFE 2021), the design the listing says it adapts. Its Net Gamma Exposure variant is not coded |

Anyone with SSRN access can drop those PDFs in here and the gap closes. Until
then the absence is the honest state, and `docs/RESEARCH/019` records what was
recovered from where.
