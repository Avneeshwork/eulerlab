# 193 · How far back Angel One's minute bars go, and what fills the gaps (2026-11-13)

**Question.** The operator wants at least 8 years of one-minute bars. Kite's
backfill holds 19 Aug 2021 onward. How far back does Angel One SmartAPI go, how
much does one request return, and can it fill the names Kite no longer lists?

**Sources.** No web search: every finding is a request to Angel's
`getCandleData` from the Mac on 2026-11-13, or a read of this repository's
stores (`data/landing/kite_minute/manifest.jsonl`, B2 `nse/kite_minute/`,
B2 `nse/cm/` UDiFF bhavcopies). Scripts were throwaway probes; the results are
below.

## Findings

1. **Stocks start 3 Oct 2016.** RELIANCE (token 2885) and HDFCBANK (1333):
   375 bars on 2016-10-03 and every probe after; zero on 2016-06-01,
   2016-09-01, and 2016-09-15..30 (the first bar of a 2016-09-15..10-05 request
   is 2016-10-03 09:15). **Indices go further:** Nifty 50 (99926000) returned
   full days in Jan 2015 and Sept 2016. So 8 years (from Nov 2018) needs no
   other source; Angel gives about 10 years for stocks.
2. **One request returns at most 8,000 candles, and drops the earliest beyond
   that without an error.** RELIANCE 2021-05-01..06-30 and 2021-06-01..06-30
   both came back with exactly 8,000 bars starting 2021-06-01 13:25; 2017-03
   (23 sessions) the same. 21 sessions x 375 = 7,875 fits. The backfill asks
   for calendar months and splits a month of more than 21 weekdays at the 15th;
   a reply of 8,000 is refused, never landed.
3. **Angel serves tokens NSE has delisted.** On 2023-06-01: IDFC (11957),
   TATAMTRDVR (16965), TV18BRDCST (14208), DHANI (15384), JPASSOCIAT (11461)
   and PEL (2412) each returned a full day. Their tokens come from NSE's own
   UDiFF CM bhavcopy (`FinInstrmId`) of 2024-07-08, 2024-09-02 and 2024-12-02.
   HDFC, MINDTREE and TATACOFFEE left before UDiFF started (July 2024), so no
   token was found and they are not fetched. **Not found: any source here
   for their tokens.**
4. **Most of the 30 "never fetched" names are renames already held.** The new
   symbol keeps NSE's token, so Kite's history under the new name runs back to
   2021: ZOMATO/ETERNAL 5097, TATAMOTORS/TMPV 3456, GMRINFRA/GMRAIRPORT 13528,
   HBLPOWER/HBLENGINE 13966, IBULHSGFIN/SAMMAANCAP 30125, SWANENERGY/SWANCORP
   27095, LTIM/LTM 17818, GUJGASLTD/GUJENERGY 10599, INFIBEAM/CCAVENUE 16249
   (Kite token / 256 = NSE token).
5. **The two vendors adjust old prices differently.** RELIANCE 2021-08-20
   15:29 close: Kite 1,020.00, Angel 1,074.13 (the pre-bonus price was about
   2,147). TMPV the same minute: Kite 193.90, Angel 171.38. Volumes differ too.
   Stitching Angel's 2016-2021 bars onto Kite's 2021+ bars would put a false
   jump at 19 Aug 2021, so they land in `data/landing/angel_minute_history`,
   and no reader opens that tree until a rule for it is chosen (T-4605).
6. **Angel serves closing-auction minutes Kite does not.** For an F&O stock
   after the 15:14 continuous close, Angel adds bars 15:20 to 15:28 or 15:29
   with near-constant volume (RELIANCE 13 Nov: about 0.5 million each minute).
   Kite stops at 15:14. 217 of 415 stocks are affected (T-4606).
7. **The review's gap list read failures, not holdings.** `unresolved.jsonl`
   is append-only; its 347 TokenExceptions on 8 Nov and the URLError days were
   refetched later. Against the manifest, and B2 holding all 36,238 of its
   files: 26 Aug to 2 Oct 2026 is held for all 414 fetched names (Kite's
   chunk 2026-08-03..10-01, landed 7 Oct). The real gaps were 9 and 13 Nov
   (217 F&O stocks each, HISTORY) and 12 Nov (3 names).

## Decision

Fill 9, 12 and 13 Nov into `kite_minute`. Backfill 3 Oct 2016 to 18 Aug 2021
for the 444-name union, the three indices and six delisted names, plus the
delisted names to today, into `angel_minute_history`, newest month first:
about 50,000 requests at one a second.

**Confidence.** High on findings 1 to 4 and 7 (direct measurement). Medium on
5's cause: the size of the gap fits a demerger adjustment (Jio Financial for
RELIANCE, the CV demerger for TMPV) in Kite and not in Angel, but neither
vendor documents its rule here.

**Open questions.** Which adjustment Kite applies, so the two can be joined;
whether the union universe (top 250 by turnover, 2021-2026 year-ends) is the
right list before 2021, when other names were large.
