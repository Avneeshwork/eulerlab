# 194 — How far back NSE's free daily files go

**Date:** 2026-11-14 · **Confidence:** high (every file fetched from the Mac and landed or rejected by the repo's own checks)

**Question.** Can the daily NSE history (bhavcopy, F&O bhavcopy, delivery, index closes, corporate actions) be lengthened from 2015 back to 15 years or more, from the same free archive?

**Sources** (fetched 2026-11-13 and 2026-11-14 with `ingest/nse_urls.url_for` and `ingest/nse_daily_files`, about 1 s apart):
- `https://nsearchives.nseindia.com/content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip`
- `https://nsearchives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip`
- `https://nsearchives.nseindia.com/archives/equities/mto/MTO_DDMMYYYY.DAT`
- `https://nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv`
- `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=01-01-YYYY&to_date=31-12-YYYY`

**Findings** (sessions landed per year; median rows a day):
- **cm**: every year from 2000-01-03, 242-252 sessions. Median rows 965 (2000), about 720 (2003), 1,599 (2014). Same 13-column legacy schema throughout.
- **fo**: from 2000-06-12 (124 sessions that year), full years after. Median rows 57 (2001) to 33,013 (2011).
- **delivery**: none in 2000-2001. In 2002 the first 30 sessions use an older layout the parser rejects ("malformed"); 216 sessions land. Full years from 2003.
- **indices**: no file before 2012 (404). 2012 to February 2013 name the Nifty "S&P CNX Nifty"; accepted since ADR-186. About 35-43 indices a day.
- **corporate actions**: one answer a year from 2000. Rows: 218, 200, 104, 70, 77 for 2000-2004, then 829 (2005) rising to 1,931 (2014).

**Not found.** Index closes before 2012 from this archive. Delivery for 2000-2001. Why 2002-2004 corporate actions are so few (A-143).

**Decision.** Landed 2000-2014 for all five (877 MB, all in B2, `make check-landing` green). Prices before 2005 may be under-adjusted.

**Open questions.** Whether another free source has index closes before 2012, and pre-2005 corporate actions.
