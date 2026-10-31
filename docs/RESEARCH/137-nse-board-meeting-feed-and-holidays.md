# 137 — Where can the brief get results dates and NSE holidays?

**Date:** 2026-10-31 · **Confidence:** high for what the two endpoints returned from the Mac today; low on how complete a forward-built results calendar is.

## Question

The rebuilt brief (ADR-105) must list results due, especially for held stocks, and must not run on non-trading days. Which official sources give results dates and holidays?

## Sources

| Source | URL | Fetched | Result |
|---|---|---|---|
| NSE board meetings RSS | https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml (listed on https://www.nseindia.com/rss-feed) | 2026-10-31 from the Mac | 200, RSS 2.0 served as text/html; 124 items, all dated 31-Oct-2026. 70 mention financial results. Each item gives the company name, a description ending "Meeting Date: DD-Mon-YYYY" and a link to the intimation |
| NSE holiday master | https://www.nseindia.com/api/holiday-master?type=trading | 2026-10-31 | 200 JSON after a session visit; 20 trading holidays for 2026, 2026-01-15 to 2026-12-25 |

## Findings

1. The board-meetings feed carries only the day's new intimations, with no back catalogue. A results calendar must be built forward by landing the feed daily. Meetings announced before capture began are missed, and the brief says so.
2. Items name the company, not the symbol. Matching names against `data/derived/nse_names.json` found symbols for 85 of 124 on the first day. Most of the rest were SME listings.
3. The holiday endpoint returns the current year only (A-012). `make holidays` runs in `make daily` so the list follows NSE's updates.

## Decision

`ingest/board_meetings.py` (`make board-meetings`, in `make daily`) and `ingest/holidays.main` (`make holidays`). The brief reads both.

## Not found

- Any free official archive of past board meetings.
- A feed of results-meeting outcomes (the results themselves come through corporate announcements, already captured).
