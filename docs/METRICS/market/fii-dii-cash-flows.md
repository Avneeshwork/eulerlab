# FII/DII cash-market flows

*Family: Market context. Id: `fii-dii-cash-flows`.*

**In one line:** Rupees foreign and domestic institutions bought minus sold in the cash market, per day.

**Where you see it:** Big money tab panel; brief scorecard row Cash flows; `/api/fii-dii`.

**How we compute it:** NSE's provisional figures: buy, sell and net per group, ₹ crore. We add net over 5 sessions, month to date, and the run of same-sign days (`ingest/fii_dii_cash.summary`).

**Data and freshness:** NSE's evening release (`make fii-dii`), backfilled from Trendlyne to 2025-10-01 (ADR-099). 266 days held.

**What is normal (our data, as of 2026-10-30):** Since 2025-10-01: FII net median −₹1,305 cr a day (5th-95th −₹8,692 to +₹2,814); DII median +₹3,159 cr. FII 5-day net median −₹6,110 cr (5th-95th −₹35,598 to +₹4,558).

**How to read it:**

- FIIs have been steady net sellers and DIIs steady buyers for the whole year; a single day is noise against that.
- Streaks and the 5-day sum matter more than one day.
- Research 104: FII flow is not an intraday entry signal on our data.

**What it does not tell you:** Derivatives positions (see participant long share), or who the buyers were within each group.

**Traps:**

- Provisional: NSDL's final FPI figures differ (T-4239).
- The brief's ±₹5,000 cr thresholds (A-082) sit near this year's median FII 5-day net, so 'weak' would have been the usual reading. The levels need review.

**Related:**

- [participant-long-share](../market/participant-long-share.md)

**Sources:**

- NSE fiidiiTradeReact (research 128); Trendlyne, Groww, stockezee history (research 127).

## Example answers

**Q:** FIIs bought ₹3,599 cr today. Turning point?

**A:** One day is weak evidence. FIIs have sold on the median day this year (−₹1,305 cr). Watch the 5-day sum and the streak; a run of buying days would be new.
