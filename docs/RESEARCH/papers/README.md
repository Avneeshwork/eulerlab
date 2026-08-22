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

## Not here, and why that matters

| Paper | Status |
|---|---|
| Zarattini, Barbon & Aziz (2024), *A Profitable Day Trading Strategy For The U.S. Equity Market*, SSRN 4729284 | **Not retrievable.** SSRN returns 403 to automated fetching. `orb_in_play` is coded from the publisher's own summary and an independent third-party reproduction, which agree on every number used. Treat any result as testing *our reading* of the rule until the paper is obtained |
| Zarattini, Aziz & Barbon (2024, rev. 2025), *Beat the Market: An Effective Intraday Momentum Strategy for SPY*, SSRN 4824172 | **Not retrievable and deliberately not coded.** The noise-boundary formula was never obtained. A guessed formula attributed to a named paper is worse than an absent strategy |
| Maróy (2025), *Improvements to Intraday Momentum Strategies*, SSRN 5095349 | Not retrievable, not coded |

Anyone with SSRN access can drop those PDFs in here and the gap closes. Until
then the absence is the honest state, and `docs/RESEARCH/019` records what was
recovered from where.
