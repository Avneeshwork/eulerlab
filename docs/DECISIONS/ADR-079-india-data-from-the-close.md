# ADR-079 — Indian data from one minute after the close, minute bars standing in

**Status:** Accepted · 2026-10-26

**Context.** Operator, 2026-10-26: the Indian update ran at 19:30 (and its launchd job was not even loaded). It should update live from just after the close, show a day as missing from 15:31 if it is not in, and use minute data in place of the daily file until it arrives, and the other way round.

**Options.** (a) Move `make daily` to 15:31: AMFI NAVs and US bars are evening data, so they would land a day late. (b) A separate weekday job at 15:31 that retries only the Indian steps every 10 minutes until the bhavcopy and minute bars are in, or 21:00, keeping 19:30 for the rest. (c) Merge minute-built bars into the price panel.

**Choice.** (b), `make india-live` (`ingest/india_live.py`, launchd `com.eulerlab.indialive`). Coverage expects today's NSE data from 15:31 and reads **missing** until it lands. While the bhavcopy is missing, `ingest/provisional_daily.py` appends daily bars built from complete Kite minute sessions (`source=kite_minute`, own `knowledge_time`). When the bhavcopy lands it appends a `superseded_by` line: nothing is deleted, and `read(as_of)` still returns what was known before. If the bhavcopy is in and the minute bars are not, the daily data is used and the minute row says what is missing. Minute bars cannot be made from daily ones. Not (c): the panel, backtests and paper books read only the bhavcopy. A minute close is the last trade, not NSE's 30-minute weighted close (0.26% apart at the median on 23 Oct 2026), and it covers 413 of about 2,300 stocks.

**Why.** No new dependency. Each pass is the feed's own steps under the `feed` lock, so it can't double-fetch or race the button.

**Cost if wrong.** If NSE's files arrive after 21:00, the 19:30 job is the last chance that day. The paper books still wait for the bhavcopy, so on a slow day they trade later than 15:31.
