# 180 — How much of each daily-bar edge is in the auction prints

**Question.** Research 173-179 fill every trade at the official open and
close: the pre-open call auction and the closing average. H-0194 screened at
a net Sharpe of 7.8, which is not believable; its five best names were ETFs,
whose opening prints are stale (research 071). How much of each PROMOTE is
in those prints rather than in a price one could trade at 09:20 and 15:10?

**Method.** Information only, no trial. (1) Drop ETFs (ISIN starting INF,
527 symbols) and re-score. (2) For each rule's trades in stocks that have
minute snapshots (research 161, F&O stocks), compare the gross move from the
official open to the close with the move from the 09:20 fill to the 15:10
fill on the same trades.

## Results, 2026-11-08

| Card | ETF trades | Without ETFs: net bps, Sharpe | Trades with minute data | Gross, open to close | Gross, 09:20 to 15:10 |
|---|---|---|---|---|---|
| H-0161 thin-rally fade | 3 | 34.0, 2.29 | 1,797 of 9,867 | 29.0 | **28.8** |
| H-0168 results-morning gap fade | 0 | 48.1, 1.91 | 633 of 1,077 | 45.9 | **1.2** |
| H-0187 results reaction, next day | 0 | 66.6, 2.58 | 516 of 935 | 61.7 | **34.9** |
| H-0185 lower-limit bounce | 0 | 88.6, 0.73 | 59 of 568 | 114.5 | 171.4 |
| H-0194 no-news gap fade | 289 | 97.7, 6.05 | 1,587 of 4,828 | 87.4 | **41.2** |
| H-0175 thin-delivery gap-up fade (autopilot) | 137 | 74.0, 3.66 | 1,283 of 8,234 | 56.6 | **43.2** |

## Findings

1. **H-0161 does not depend on the auction prints**: 29.0 bps from the open,
   28.8 from 09:20. It is the most robust result in the library.
2. **H-0168's edge is entirely in the opening auction.** From 09:20 it makes
   1.2 bps gross, below the 12.24 bps cost. It is tradable only by entering
   in the pre-open auction (09:00-09:08) on the indicative gap, which this
   project has never tested. Treat H-0168 as unproven until that is.
3. **H-0187, H-0194 and H-0175 keep about half to three quarters of their
   gross edge at 09:20** (34.9, 41.2, 43.2 bps): still above cost at 1x, but
   their backtests overstate them by 1.3x to 2.1x.
4. **ETFs inflated H-0194 and H-0175** (stale opening prints); the screens'
   universe should exclude INF ISINs. Without them H-0194's Sharpe is still
   6.05, which the open-print effect, not skill, most likely explains.
5. These are F&O stocks only; the smaller stocks that dominate the rules
   have no minute data here, and their auction prints are likely worse.

## Decision

The paper books that fill at the official open (H-0161, H-0168, H-0187) are
priced the way their backtests were; the live-price shadow (ADR-153), which
fills at live quotes, is the fair test. H-0168 should not be expected to make
money from 09:20.
