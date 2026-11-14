# 195 — NSE's symbol-change list as identity history before 2011

**Date:** 2026-11-14 · **Confidence:** high that the file exists and parses; medium that it is complete before 2005

**Question.** Is there a free, primary record of NSE symbol changes to give pre-ISIN bhavcopy rows a point-in-time identity?

**Sources** (fetched 2026-11-14, one request each, from the Mac):
- `https://nsearchives.nseindia.com/content/equities/symbolchange.csv` — 200, 70 KB, 1,080 changes. Columns: company, old symbol, new symbol, effective date (DD-MON-YYYY). Earliest seen 2003 (MASCOT to IGS, 07-AUG-2003); latest 2025.
- `https://nsearchives.nseindia.com/content/equities/namechange.csv` — 200, 242 KB, 2,344 company-name changes by symbol. Not used: a name change keeps the symbol.
- Legacy bhavcopy headers: no `ISIN` column on 2011-06-01; present on 2011-12-01 (`...,TOTALTRADES,ISIN,`).

**Findings.** The change list goes back to 2003 but not to 2000, so a 2000-2002 change would not be seen; the continuity rule (no gap over 60 sessions) and the takeover rule catch most consequences. NSE does not publish a list of symbols reused after a delisting.

**Decision.** ADR-187: land the file raw (`nse/symbol_changes`) and resolve pre-ISIN rows through it, leaving out what does not resolve.

**Result of the build into a copy (2026-11-14, `data/derived/rebuild-2026-11-14/`).**
4,159,085 rows for 2000-2014; the first ISIN-bearing day is 2011-06-22. 1,281,012 rows had an ISIN; 2,349,152 rows (1,495 instruments) reached one through the chain; 484,627 rows (1,013 instruments) never did and have their own `NOISIN` id, recorded in `instruments_no_isin.jsonl`; 44,294 rows were dropped as a symbol's second series row the same day (A-145; 8,730 in 2000, 35,562 in 2001, 2 in 2002). A first version that dropped no-anchor and gap rows instead kept only 489 instruments in 2000; with own ids it keeps 1,294. The 2015-onward panel is byte-identical to the live one.

**One-day moves over 40% in 2000-2014: 3,280.** 293 are covered by a price factor. 177 have a split, bonus or scheme in NSE's text but no factor: the parser reads the older "Fv Split Rs.10/- To Rs.2/-" wording as OTHER (ABB 2007-06-28, ALEMBICLTD 2006-09-26), and schemes of arrangement carry no ratio. 118 show volume moving inversely to price (an unlisted split or consolidation, e.g. ADANIEXPO 2004-07-29). 507 are one-day prints that revert next session (446 in 2000-2001, 59 in 2013-2014). 305 span a trading gap of more than 5 sessions. 1,880 are unexplained, 1,659 of them in 2000-2001, mostly stocks under Rs 10 where one tick is a large move. A-146 proposes how to treat them.

**After A-146 in the copy (ADR-188).** The parser now reads the older split wording: pre-2015 price factors rose from 411 to 575, 10 of them keyed to instruments without an ISIN. 512 were confirmed by the price move within 10% and 57 dropped. Of the 3,280 moves, 414 are confirmed splits or bonuses (293 before, so about 121 of the 177 cleared), 531 are one-day prints whose row is excluded, and 2,335 are unexplained and masked 20 sessions each side; 2,866 mask entries plus the Rs 10 floor for 2000-2003. Instruments with rows left after the mask: 1,073 (2000), 845, 819, 751, 852, 921 (2005), 1,047, 1,232, 1,303, 1,339, 1,492 (2010), 1,568, 1,592, 1,596, 1,594 (2014). Factors from 2015 and the 2015-onward panel are unchanged.

**Open questions.** Completeness of the list before 2005; a free list of delistings before 2011, which would size the survivorship gap.
