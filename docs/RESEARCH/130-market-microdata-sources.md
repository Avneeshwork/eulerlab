# 130 — Where can we get Nifty minute bars, order book data and the reports ScanX shows?

**Date:** 2026-10-30 · **Confidence:** high on the NSE addresses (each fetched from the Mac and landed); medium on how far back the insider endpoint goes; low on prices for paid order data (not published)

## Question

The operator asked for a year of Nifty 50 minute data, order book ("market
order") data, and every dataset ScanX (scanx.trade, Dhan) offers that the
platform lacks. Which can be had for free, how far back, and from where?

## Sources

| Source | URL | Fetched | Type |
|---|---|---|---|
| ScanX home and Insight menu | https://scanx.trade/ , https://scanx.trade/insight | 2026-10-30 | product site (read in a browser; plain HTTP got 403) |
| NSE Data & Analytics | https://www.nseindia.com/static/nse-data-and-analytics | 2026-10-30 (search result) | exchange |
| NSE data pricing file, domestic clients | https://nsearchives.nseindia.com//web/mediaattachment/2026-03/NSE_Pricing_file_-_Domestic_clients_20260309171343.pdf | 2026-10-30 (search result, not opened) | exchange |
| NSE bulk/block/short-selling archive page | https://www.nseindia.com/report-detail/display-bulk-and-block-deals | 2026-10-30 | exchange; network calls read in a browser |
| NSE insider trading page | https://www.nseindia.com/companies-listing/corporate-filings-insider-trading | 2026-10-30 | exchange; network calls read in a browser |
| Each report address in `src/eulerlab/ingest/nse_reports.py` | see the code | 2026-10-30 | exchange; fetched and landed |

## Findings

1. **Order book history is not free.** NSE sells historical order and trade
   data for the cash, F&O and currency markets through NSE Data & Analytics
   (ask marketdata@nse.co.in). Its real-time levels are best bid/ask (L1),
   5 levels (L2), 20 levels (L3) and tick-by-tick (full book). Paid vendors
   (Global Data Feed, TrueData) resell tick data. No price was found.
2. **Going forward, Kite streams five levels.** Full mode on the Kite
   WebSocket gives the last trade, day volume, total buy and sell quantity,
   OI and the best five bids and asks with order counts. It is a snapshot
   per change, not each order.
3. **Nifty index minutes are in Kite.** `NIFTY 50`, `NIFTY BANK` and
   `INDIA VIX` are listed on NSE with instrument type EQ in the INDICES
   segment, so the existing minute client can fetch them. The stock archive
   only held NIFTYBEES.
4. **ScanX's Insight menu** lists: stock heatmap, FII/DII, company filings,
   MF holdings, bulk/block deals, signals, SLBM, MTF, F&O ban list, top
   deliveries, market valuation, IPO, cyclical trend, events; plus about 100
   price and pattern screeners. Missing here before this work: bulk/block
   deals, F&O ban, SLBM, MTF, MF holdings, IPOs, insider trades and pledges.
   The screeners and heatmaps are rules over price data the platform holds.
5. **Bulk, block and short-selling history:**
   `/api/historicalOR/bulk-block-short-deals?optionType=...&from=&to=`.
   The JSON answer stops at **70 rows** (October 2025 bulk deals: 70 rows,
   all dated the 1st). Adding `&csv=true` returns every row (1,873 for the
   month). The old `/api/historical/bulk-deals` answered 503.
6. **Insider trades:** the page now calls `/api/corporates-pit-gg`. The old
   `/api/corporates-pit` returns `{"data":[]}` for every range tried. The new
   one returned rows for May to October 2026 and nothing for January or
   April 2026 or late 2025.
7. **SAST reg 29** (`/api/corporate-sast-reg29`) has rows in November 2025.
8. **Dated archive files present a year back:** `fo_secban_DDMMYYYY.csv`,
   `SLBM_BC_DDMMYYYY.DAT`, `mrg_trading_DDMMYY.zip` (30 Oct 2025 all 200).
   The MTF file for a day can appear only the next day. For 2026-04-08 NSE
   served it as a 0-byte file (200), so that day is missing.
9. **Snapshots only:** `corporate-pledgedata`, `ipo-current-issue`,
   `public-past-issues`, `ind_nifty50list.csv`. None takes a date.

10. **Found while building the tab (2026-10-30):** NSE's bulk list repeats a
    block trade that also passes 0.5% (Swiggy, 30 Oct: Tencent's sale is in
    both). The API answered short selling for 30 Oct with an empty 200 the
    next day: an unpublished day looks the same as a day with nothing. The
    PIT list names the filing and rule, not the size; the size is in each
    filing's XBRL.

## What could not be found

- A free source of past NSE order book data. None exists that we found.
- The price of NSE's historical order data (the pricing PDF was not opened).
- The first date `corporates-pit-gg` serves. Somewhere in May 2026.
- A single file of mutual fund holdings by stock. Each fund house publishes
  its own monthly portfolio workbook in its own layout; AMFI does not
  consolidate them that we found.
- ScanX's option chain: the Insight menu shows none.

## Decision

Land the NSE reports daily and back a year (`make nse-reports`), the three
index minute series from Kite (`make index-minute`), and record Kite depth
from now on (`make depth-day`). Mutual fund holdings are deferred (T-4224).
ADR-095.

## Open questions

- Whether to buy NSE historical order data. That is the operator's call and
  needs a price first.
- Whether NSE's terms allow storing these reports. Not read (S-044).
