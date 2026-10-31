# Index level and returns (1 day to 1 year)

*Family: Market context. Id: `index-returns`.*

**In one line:** Where an index closed and how far it moved over 1, 5, 21, 63 and 252 sessions.

**Where you see it:** Dashboard → India → Overview tiles; `/api/market-context` `strip.indices[].change`; the brief's India section.

**How we compute it:** Close over the close `n` sessions earlier, minus 1 (`market_context._change`, `index_strip`). Sessions, not calendar days: 21 is about a month, 252 about a year.

**Data and freshness:** NSE index closes in `data/derived/index_history.jsonl`, rewritten each evening; the strip shows `as_of`, the last close held. Before 15:30 IST it is yesterday's close.

**What is normal (our data, as of 2026-10-30):** Nifty 50's absolute one-day move since 2015: median 0.52%, 75th percentile 0.93%, 95th 1.87% (2,910 days). A 2% day is in the top 5%.

**How to read it:**

- Compare the indices with each other before reading any one: Nifty 50 up while Smallcap 250 is down means a few large caps carry the index.
- A one-day move is noise unless it is large against the normal range above; the month and quarter say more about direction.

**What it does not tell you:** Why it moved, or what the average stock did (see breadth).

**Traps:**

- Price indices, not total return: dividends are left out, about 1.3% a year for Nifty 50.
- The `as_of` date matters: a pre-open brief shows the previous session.

**Related:**

- [breadth-above-average](../market/breadth-above-average.md)
- [sector-relative-strength](../market/sector-relative-strength.md)
- [pulse-trend](../market/pulse-trend.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Market context on the dashboard
- NSE index history (research 002).

## Example answers

**Q:** Nifty was up 0.5% yesterday. Good day?

**A:** Ordinary. A 0.5% move is the median day since 2015. What stood out was underneath: Smallcap 250 fell 2.0% the same day, so the index gain came from a few large caps.
