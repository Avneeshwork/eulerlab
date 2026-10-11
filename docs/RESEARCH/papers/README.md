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

## Not here, and why that matters

| Paper | Status |
|---|---|
| Zarattini, Barbon & Aziz (2024), *A Profitable Day Trading Strategy For The U.S. Equity Market*, SSRN 4729284 | **Not retrievable.** SSRN returns 403 to automated fetching. `orb_in_play` is coded from the publisher's own summary and an independent third-party reproduction, which agree on every number used. Treat any result as testing *our reading* of the rule until the paper is obtained |
| Maróy (2025), *Improvements to Intraday Momentum Strategies*, SSRN 5095349 | Not retrievable, not coded |

Anyone with SSRN access can drop those PDFs in here and the gap closes. Until
then the absence is the honest state, and `docs/RESEARCH/019` records what was
recovered from where.
