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
