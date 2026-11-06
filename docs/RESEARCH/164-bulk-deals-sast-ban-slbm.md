# 164 — Five cash rules from NSE's deal, disclosure, ban and lending reports, backfilled to 2021

**Question.** Operator, 2026-11-06: "research more strategies", then, when
told the NSE reports landed only from October 2025, "we can download more old
data instead of rejecting". Cash stocks at 1x; reports read as signals.

**Status.** H-0093 to H-0097 pre-registered and committed before any run.
Results follow under "Results".

## The backfill

`make nse-reports` (research 130) landed these reports only from 2025-10-30,
inside the holdout and after the minute data ends. Probed 2026-11-06, NSE
still serves them for 2021 and 2023, so they were backfilled from 2021-07-01
with the same downloader (`python -m eulerlab.ingest.nse_reports --from
2021-07-01 --only bulk_deals block_deals sast fo_ban slbm`):

| Report | 2021-08-24 | 2023-03-21 | Used |
|---|---|---|---|
| Bulk deals | 33 rows | 57 rows | H-0093, H-0094 |
| Block deals | 0 | 0 | No: rare |
| SAST reg. 29 disclosures | 30 | 25 | H-0095 |
| F&O ban list | 4 | 2 | H-0096 |
| SLBM bhavcopy | 74 | 40 | H-0097 |
| Short selling | 2 | 1 | No: too few |
| Insider (PIT) | 0 | 0 | No: the endpoint has nothing before 2026 (research 130) |

Files from 2024-12 onward also landed (the downloader runs to today); they are
holdout-period data and are not read here.

## Sources, searched 2026-11-06

| Rule | Source | Read |
|---|---|---|
| H-0093, H-0094 bulk deals | Chaturvedula, Bang, Rastogi and Kumar (2015), "Price manipulation, front running and bulk trades: evidence from India", *Emerging Markets Review* 23, 26-45 ([RePEc](https://econpapers.repec.org/RePEc:eee:ememar:v:23:y:2015:i:c:p:26-45)); "What's hidden behind bulk deals?", *Managerial Finance* 2022 ([Emerald](https://emerald.com/insight/content/doi/10.1108/MF-08-2021-0374/full/pdf)) | Abstracts: buy trades carry positive abnormal returns, stronger than sells; most of the move comes *before* the deal (front-running), and volume falls after it |
| H-0095 promoter buying | Indian insider-trading thesis, BSE 2007-2015 ([NITK](https://idr.nitk.ac.in/items/2e0597cb-33a1-4f4d-bfd2-6970ede2914a/full)) | Abstract: insider purchase portfolios earn positive abnormal returns. No study of SAST promoter disclosures alone was found |
| H-0096 F&O ban entry | Broker explainers only (e.g. [ICICI Direct](https://www.icicidirect.com/ilearn/stocks/articles/future-and-options-ban-impact-on-stock)) | They call the ban bearish: no new longs can be opened. No academic test was found |
| H-0097 stock borrowing | Boehmer, Jones and Zhang (2008), "Which shorts are informed?", *J. Finance* 63(2), 491-527 ([RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:63:y:2008:i:2:p:491-527)) | Abstract: heavily shorted stocks underperform by 1.16% over 20 days (NYSE daily short flow) |

## The rules, fixed before running

Reports for session t are read only from session t+1 (bulk deals, SLBM and
SAST are published in the evening). Trades are 09:20 to 15:10 on the stated
session, ₹1 lakh a position, 1x, cash-intraday charges plus 2 bps a side, at
most ten a day, F&O stocks with Kite minute bars, to 2024-11-29.

1. **H-0093 bulk-deal buyers.** On t, a client that both bought and sold a
   stock is ignored (intraday churn). If the remaining buys' value exceeds the
   remaining sells', buy on t+1; largest net value first.
2. **H-0094 bulk-deal sellers.** The same, net sells: short on t+1.
3. **H-0095 promoter buying.** A SAST disclosure with promoter flag Y and type
   "Acquisition": buy on the first session that opens after the disclosure
   time (a disclosure during 09:15-15:10 counts for the next session); largest
   percentage acquired first.
4. **H-0096 F&O ban entry.** A stock in the ban list for trade date t that was
   not in it for t-1: short on t.
5. **H-0097 heavy borrowing.** SLBM quantity traded on t times the stock's last
   close, over its 20-session mean cash traded value: when 0.5% or more, short
   on t+1; largest ratio first.

Judged as before: positive net in both halves (before 2024, and 2024). No
trial spent.

## Confidence

Low. The bulk-deal studies find most of the move before the deal, which a
next-day trade cannot catch. H-0096 has no academic support. SLBM is also used
for arbitrage and around dividends, not only to short.

## Results (run 2026-11-06, after the rules were committed in `6ef07fe`)

Backfill: bulk deals, SAST, F&O ban and SLBM landed for every session from
2021-07-01 (6,375 manifest lines, all parse). The ban list has a file for
each of the 807 sessions in the window. `make nse-reports-intraday` →
`data/derived/nse_reports_intraday.json`. 1x; no trial spent.

| Rule | Trades (events) | Gross a trade | Net a trade | Net Sharpe | Before 2024 / 2024 (net Sharpe) |
|---|---|---|---|---|---|
| H-0093 bulk-deal buyers | 144 (4,237) | -23.52 bps | -35.77 bps | -0.83 | -0.70 / -1.16 |
| H-0094 bulk-deal sellers | 298 (6,465) | 14.75 bps | +2.49 bps | 0.08 | -0.00 / 0.32 |
| H-0095 promoter buying | 331 (3,590) | -25.38 bps | -37.65 bps | -1.78 | -1.69 / -2.16 |
| **H-0096 F&O ban entry, short** | **567 (664)** | **45.46 bps** | **+33.22 bps** | **1.49** | **1.26 / 1.97** |
| H-0097 heavy borrowing | 6,949 (9,514) | 5.98 bps | -6.37 bps | -1.11 | -0.99 / -1.38 |

(Events are F&O stocks and others; trades need a Kite minute file and are
capped at ten a day.)

**H-0096 passes the screen**, the first of 57 intraday rules in research
153-164 to do so. Shorting a stock on its first day in the F&O ban, 09:20 to
15:10:

| Check | Result |
|---|---|
| Per trade | mean 45.5 bps gross, median 50.3, t = 4.22 (567 trades) |
| Minus the Nifty's 09:20-15:10 move the same day | 37.9 bps, t = 3.67 |
| By year (mean gross, trades) | 2021 94.0 (59), 2022 31.6 (83), 2023 31.5 (167), 2024 47.8 (258) |
| Net, by year | every year positive; max drawdown -2.6% of ₹10 lakh |
| Breadth | 55 stocks on 377 days; the largest contributor (NATIONALUM) is 6% of the total |
| Without the 10 best trades | 31.3 bps gross; without the best 5%, 14.6 |
| Multiple testing | t 4.22 survives a Bonferroni correction for 57 tests (p ≈ 0.001) |

The rest:

- **Bulk-deal buys and promoter buying are followed by falls** (-24 and -25
  bps): the buying is done and the price has already moved, as the bulk-deal
  studies found (front-running before the deal).
- **Bulk-deal sells** fall a little further next day (14.8 bps), too little.
- **Heavy SLBM borrowing** is 6 bps, below costs; SLBM is mostly arbitrage.

**What is not yet known about H-0096.**

1. **When the ban list is public.** The rule needs the list for trade date t
   before 09:20 on t. The ban is set from end-of-day open interest and applies
   from the next session, and news sites publish "stocks in F&O ban today"
   before the open, but this project has never fetched the file before the
   open: its collector fetches each day after 21:00 (A-114, T-4475).
2. **Shorting.** The trade is an intraday cash short (MIS), squared off the
   same day, which needs the stock to be shortable intraday at the broker.
   F&O stocks are; a banned stock's cash segment trades normally.
3. **Fills.** 09:20 entry and 15:10 exit at the minute open, plus 2 bps a side
   slippage, as every screen here. Banned stocks are volatile at the open.
4. **2025 onward** is the holdout and has not been read.

## The gate (2026-11-06, operator's instruction)

The operator asked for H-0096 to be gated, and for the holdout to October
2026 to be read only if it passed. `make validate` gained an intraday route
for this (ADR-139). Validation (ledger #64) then the gate (ledger #65):
**KILL, 3 of 12 rules failed.**

| Rule | Result | Mandate |
|---|---|---|
| Deflated Sharpe | 0.784 | >= 0.95 — **fail** |
| Romano-Wolf over Nifty | -0.51 vs critical 1.73 | **fail** |
| Stress: drop best 5 names | 44% of Sharpe kept (1.49 -> 0.66) | >= 60% — **fail** |
| Search bar | 28 families, bar Sharpe 1.05 | pass |
| Backtest length | 3.2 years vs 0.5 needed | pass |
| Stress: 2x costs | 64% kept | pass |
| Stress: worst regime | first half 1.13, second 1.78 (76%) | pass |
| Entry 5 minutes late | 72% kept | (reported) |
| Costs x3 | 27% kept, still positive | (reported) |

The holdout was **not read**. Under CLAUDE.md the strategy is dead and is not
tuned or resubmitted.

Two things for the operator, not arguments with the gate:

- **Romano-Wolf measures return over the Nifty with beta 1.** For a rule that
  is short a few stocks on 47% of days and flat otherwise, that subtracts the
  whole index's rise from a strategy with little market exposure. Whether the
  mandate should use the strategy's own beta for intraday rules is a mandate
  question (proposal only).
- **The concentration failure is real.** Five stocks (NATIONALUM, ZEEL, IRCTC,
  RBLBANK, HINDCOPPER), bans that recur, carry over half the Sharpe.
