# 183 — NSE special and short sessions (Muhurat 2026-11-08)

**Question.** NSE opened on Sunday 2026-11-08 for Diwali Muhurat trading. Why did the data not have it, what else is missing, and how should backtests treat a short session?

**Sources.**
- Outlook Money, "Diwali Muhurat trading 2026: NSE schedules rare afternoon session on November 8", fetched 2026-11-08: normal market 14:20-15:30 IST, trade modification until 15:40, citing NSE circular NSE/COM/71784 of 2025-12-15. https://www.outlookmoney.com/invest/diwali-muhurat-trading-2026-nse-schedules-rare-afternoon-session-on-november-8-check-full-schedule
- Business Today, 2026-10-19, same date and session. https://www.businesstoday.in/markets/stocks/story/muhurat-trading-2026-nse-bse-announce-diwali-timings-check-full-schedule-562486-2026-10-19
- Not found: the NSE circular itself (nsearchives PDFs did not open). The session's existence is confirmed by primary evidence instead: NSE published a cash bhavcopy (3,550 rows) and an F&O bhavcopy for 2026-11-08.

**Findings.**
1. Every NSE downloader walked weekdays only (`nse_eod.business_days`, used by the bhavcopy, index-close, delivery, participant-OI and report steps; `kite_minute.uncovered_chunks` for minute bars). The calendar of 2,925 trading days held no Saturday or Sunday.
2. Probing every Saturday and Sunday 2015-01-01 to 2026-11-08 against NSE's archive found 12 sessions, all with cash and F&O files: 2015-02-28 (Budget), 2016-10-30 (Muhurat), 2019-10-27 (Muhurat), 2020-02-01 (Budget), 2020-11-14 (Muhurat), 2023-11-12 (Muhurat), 2024-01-20 (full special session), 2024-03-02 and 2024-05-18 (disaster-recovery drills), 2025-02-01 (Budget), 2026-02-01 (Budget), 2026-11-08 (Muhurat). No probe failed.
3. Weekday Muhurat sessions (2015-11-11, 2017-10-19, 2018-11-07, 2021-11-04, 2022-10-24, 2024-11-01, 2025-10-21) were held, but as ordinary days.
4. Total panel turnover against the median of the 20 sessions before it: short sessions 0.10-0.27, Muhurat 2026-11-08 0.39 (an afternoon hour, busier than the evening ones), 2017-07-10's late open 0.27. Lowest full day 0.59 (2021-02-24, NSE's outage), then New Year's Days 0.60-0.67. Budget Saturdays and 2024-01-20 score 0.76-1.09. Nifty 50 index turnover separates the earlier sessions too, but its lowest normal day is 0.42 (2016-01-01), so the panel is the measure used.
5. Replaying every active paper book on a copy of its folder (scratch, Telegram off): with the new engine and the real panel, `nse_github_weinstein_stage2` (fc4b65) halts, because on 2026-11-08 at 21:17 IST the old engine already filled four sells at the Muhurat close and the new one would fill them on 2026-11-09. With the 2023-2026 weekend sessions also added to the panel, `india_sharpe_momentum_opt` (25375c) halts too: the added 2026-02-01 row moves its lookback, so a 2026-10-16 order changes. Every other book was unchanged.

**Decision.** ADR-157: probe weekends nightly, let the other feeds follow, flag short sessions at 50% (A-129), and hold through them in the engines. The six weekend days from 2023 on are held out of the price panel by the quarantine (`make data-quality` shows them) until the operator decides; the pre-2023 ones are outside the panel build's default window.

**Confidence.** High that the sessions are complete (every weekend probed). Medium on the 50% line: the gap between 0.39 and 0.59 is the whole margin.

**Minute bars from Angel One (2026-11-09).** The Kite token had expired, so on the operator's instruction the 2026-11-08 minute bars came from Angel One SmartAPI's `getCandleData` (`ingest/angel_minute.py`, `make angel-minute FROM=`), landed in `data/landing/angel_minute` in the Kite layout. Bars run 14:20 to 15:29 IST. NIFTY 50 and NIFTY BANK return 56 bars and INDIA VIX 70, so Angel's index series has gaps in this session; not investigated. SmartAPI refused requests 0.4 s apart (`exceeding access rate`) although it documents 3 a second; 1 s with backoff holds.

**Open.** NSE reports (deals, short selling, SLBM) for the older weekend sessions were not backfilled. A paper book replay does not respect `knowledge_time`, so any backfill of past days can change a live book; that is a wider gap than this note.
