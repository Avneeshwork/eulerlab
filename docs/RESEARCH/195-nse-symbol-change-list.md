# 195 — NSE's symbol-change list as identity history before 2011

**Date:** 2026-11-14 · **Confidence:** high that the file exists and parses; medium that it is complete before 2005

**Question.** Is there a free, primary record of NSE symbol changes to give pre-ISIN bhavcopy rows a point-in-time identity?

**Sources** (fetched 2026-11-14, one request each, from the Mac):
- `https://nsearchives.nseindia.com/content/equities/symbolchange.csv` — 200, 70 KB, 1,080 changes. Columns: company, old symbol, new symbol, effective date (DD-MON-YYYY). Earliest seen 2003 (MASCOT to IGS, 07-AUG-2003); latest 2025.
- `https://nsearchives.nseindia.com/content/equities/namechange.csv` — 200, 242 KB, 2,344 company-name changes by symbol. Not used: a name change keeps the symbol.
- Legacy bhavcopy headers: no `ISIN` column on 2011-06-01; present on 2011-12-01 (`...,TOTALTRADES,ISIN,`).

**Findings.** The change list goes back to 2003 but not to 2000, so a 2000-2002 change would not be seen; the continuity rule (no gap over 60 sessions) and the takeover rule catch most consequences. NSE does not publish a list of symbols reused after a delisting.

**Decision.** ADR-187: land the file raw (`nse/symbol_changes`) and resolve pre-ISIN rows through it, leaving out what does not resolve.

**Open questions.** Completeness of the list before 2005; a free list of delistings before 2011, which would size the survivorship gap.
