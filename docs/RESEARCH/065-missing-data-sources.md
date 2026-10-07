# 065 — Data the Indian-equity papers needed that the platform does not hold

**Question.** Of the 42 papers in the research library, 14 could not be
backtested, and several that were ran on proxies. What data is missing, where
can it be had free from a primary source, and what would each unlock?

**Sources, fetched 2026-10-07** (status code and size checked with a browser
user agent):

| Source | URL pattern | Checked | Result |
|---|---|---|---|
| NSE index closes, every index, daily | `https://nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv` | 04-01-2016, 02-01-2024 | 200; 5-11 KB; 13 columns: open, high, low, close, volume, turnover, **P/E, P/B, dividend yield**. 2016 file lists 58 indices including Nifty Bank, Auto, IT, Pharma, Metal, Realty, FMCG, Midcap 100, Smallcap 100 and **India VIX**; 2024 adds Midcap 150, Smallcap 250 |
| NSE delivery position, daily | `https://nsearchives.nseindia.com/archives/equities/mto/MTO_DDMMYYYY.DAT` | 04-01-2016 | 200; 58 KB; per security: traded quantity, deliverable quantity, delivery % |
| NSE full bhavcopy with delivery | `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv` | 2016 / 2020 / 2021 / 2024 | 404 for 2016; 200 from 2020. The MTO files cover the earlier years |
| NSE PR archive, daily | `https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PRDDMMYY.zip` | 04-01-2016, 02-01-2024 | 200; contains book closures (Bc), announcements (An), 52-week highs/lows (bh), ETF prices (etf). No market-cap file |
| NSE current index constituents | `https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv` | today | 200; current list only, not history |
| NSDL FPI daily investment reports | `https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx` | today | 200; the page lists daily FPI equity and debt flows |
| Kite historical candles | `https://kite.trade/docs/connect/v3/historical/` | today | 200; documents daily and minute candles for any instrument token, indices included; the platform already has Kite credentials |

**Already landed but not used.** The cash bhavcopies in the landing zone (B2,
2015 onwards) carry OPEN, HIGH and LOW in both the legacy and UDiFF formats.
The price panel stores only the close for dates before 2026-08-18, because the
fields were added later and rebuilding meant re-reading every file (T-3973's
note in `features/panel.py`). The F&O bhavcopies carry every contract's
expiry date, so the true expiry calendar is already on disk.

## Findings: what is missing, and what it unlocks

| # | Data | Source | Unlocks |
|---|---|---|---|
| 1 | All NSE index OHLC, P/E, P/B, yield, incl. India VIX and sectoral indices | `ind_close_all` (one ~8 KB file a day) | Sector rotation (Sharma 2025); VIX + candle gap signal (Mukherjee 2025); lead-lag on the real Midcap/Smallcap indices (Sahoo 2022); index-level valuation timing; honest index benchmarks |
| 2 | Daily open, high, low for every stock before Aug 2026 | Already in the landed bhavcopies: rebuild the panel | Candlestick patterns (Manoharan 2019); ATR, Donchian and true ranges in the builder; overnight vs intraday decomposition on daily bars (Knuteson 2020) |
| 3 | Delivery quantity and delivery % | `MTO_*.DAT` (2016+), `sec_bhavdata_full` (2020+) | Delivery-volume signals, a standard Indian retail indicator absent from every strategy here |
| 4 | Exact F&O expiry calendar and exchange holidays | Derived from landed F&O and cash bhavcopies | Replaces the rule-based expiry and panel-derived holidays (A-041) |
| 5 | FPI (FII) daily net flows | NSDL FPI reports | FII-flow papers; none could be tested |
| 6 | ETF corporate actions | NSE PR archive book closures; else the AMC notices | Catches splits like NIFTYBEES 2019 (A-043) in the other ETFs |
| 7 | Point-in-time index membership | NSE/niftyindices index-change press releases | True Nifty 50/100/500 universes instead of the turnover proxy (HISTORY #16) |
| 8 | Shares outstanding / market cap, point-in-time | NSE shareholding-pattern filings (quarterly, dated) | Size, value weighting, Fama-French factors, turnover ratio |
| 9 | Fundamentals with announcement dates | NSE financial-results filings (XBRL, broadcast time) | Value, quality, earnings drift; the screener data has no knowledge time (T-809) |

## Decision

Proposed to the operator: 1-4 first (free, small, mechanical, and they unlock
five papers already in the library); 5-6 next; 7-9 are each a project.

## Confidence

High that 1-4 exist and respond (fetched). Medium on how far back
`ind_close_all` and the MTO files go before 2016 (not probed). Not checked:
NSE rate limits on a multi-year backfill; NSDL's historical archive format.

## Open questions

- Does NSE's book-closure file list ETF unit splits?
- A market-cap source with daily history and no login.

## Built (2026-10-07): items 1-4

- **Expiries.** 144 Nifty monthly expiries, January 2015 to December 2026,
  one per month, from F&O bhavcopies fetched from NSE's archive. Sampling
  alone was wrong twice: the union of scheduled dates held 2023-06-29 (the
  expiry moved to the 28th when the Bakri Id holiday moved to the 29th) and
  2025-09-25 (moved to the 30th when Nifty expiry became Tuesday). Each date is
  now confirmed by its own day's file (`confirm_expiries`). The confirmed list
  agrees with the weekday rule on every past month; the rule's only error was
  marking the last day of an incomplete month at the end of the panel.
- **Index closes.** 2,894 days landed, 2015-01-01 to 2026-10-06; 177 indices
  once renamed ones are joined. Nine trading days have no file at NSE (404,
  retried): 2015-02-02, 2015-03-12, 2015-03-13, 2015-05-19, 2015-07-08,
  2015-09-04, 2015-10-16, 2015-12-01, 2016-06-20. NSE renamed 48 indices on
  2015-11-09 ("CNX Midcap" became "Nifty Midcap 100", "NI15" became "Nifty
  Growth Sectors 15"), and from April 2016 the Midcap and Smallcap 100 appear
  under two spellings on alternating days. Each pair was matched by closing
  level across the rename (all within 2.2%) and joined into one series; the
  worst one-day move in every joined series is a real market day (2020-03-23,
  2024-06-04), not a seam.
- **Delivery.** 2,903 days, every trading day in the calendar.
- **OHLC.** All 2,898 panel days re-read from NSE's archive. 5,378,038 rows,
  every stored close reproduced exactly; the panel was swapped and the
  close-only file kept beside it.
- **Calendar.** 2,902 trading days and 166 weekday closures, 2015-01-01 to
  2026-10-05.
