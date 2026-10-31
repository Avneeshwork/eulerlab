# Point in time (event time and knowledge time)

*Family: Data quality. Id: `point-in-time`.*

**In one line:** Every record says when it happened and when we knew it, so research never sees the future.

**Where you see it:** Every stored table; the research read API's `as_of`.

**How we compute it:** `event_time` and `knowledge_time` on each record; reads drop rows known after `as_of` (`docs/ARCHITECTURE.md` §3.2).

**Data and freshness:** All derived tables.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- A source with `point_in_time: false` (screener.in fundamentals) can leak results before they were announced (A-066).

**What it does not tell you:** Accuracy.

**Traps:**

- Backfilled history is known only from its scrape time.

**Related:**

- [data-grade](../quality/data-grade.md)

**Sources:**

- `docs/ARCHITECTURE.md` §3.2.

## Example answers

**Q:** Can a backtest use today's fundamentals for 2019?

**A:** Not safely: the fundamentals source cannot date when each figure was known, so a 2019 test could see results before they were public.
