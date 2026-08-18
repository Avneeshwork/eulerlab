# 003 — Can Kite Connect snapshot full Nifty and Sensex chains every 5 seconds?

**Sprint:** 2 (research done early) · **Date:** 2026-08-18 · **Confidence:** high

## Question

Sprint 2's acceptance criteria call for snapshots of the **full** Nifty and
Sensex option chains every 5 seconds. A-008 assumed Kite permits this without
checking. It is the first task of Sprint 2 because if the answer is no, the
recorder's design changes before a line of it is written.

## Sources

| Source | URL | Fetched |
|---|---|---|
| Kite WebSocket streaming | https://kite.trade/docs/connect/v3/websocket/ | 2026-08-18 |
| Kite market quotes + limits | https://kite.trade/docs/connect/v3/market-quotes/ | 2026-08-18 |
| Kite rate limits | https://kite.trade/docs/connect/v3/exceptions/ | 2026-08-18 |
| Kite instrument master (public, unauthenticated) | https://api.kite.trade/instruments | 2026-08-18 |

The instrument dump is 9.3 MB / 114,427 rows and was downloaded and counted, so
the chain sizes below are measured rather than estimated.

## Findings

### The chains are 4,138 instruments

| Underlying | Exchange | Option contracts | Expiries | Nearest expiry |
|---|---|---|---|---|
| NIFTY | NFO | 1,726 | 18 | 2026-08-18, 210 contracts |
| SENSEX | BFO | 2,412 | 19 | 2026-08-20, 268 contracts |
| **Total** | | **4,138** | | |

### Polling cannot do it. Streaming can, easily.

| Approach | Documented limit | Full chain in one pass |
|---|---|---|
| REST `/quote` | 500 instruments per call, **1 request/second** | 9 calls → **9 seconds** |
| WebSocket | **3,000 instruments per connection**, 3 connections per API key | subscribe once, then no polling at all |

**A 5-second poll of the full chain is arithmetically impossible** — one pass
takes nine seconds at the documented rate limit, and that is before any retry
or jitter. Chasing it by trimming to near expiries would work (478 contracts,
one call) but throws away exactly the far-dated data that makes a surface
reconstructable later.

**The WebSocket resolves it completely.** 4,138 instruments fit in two of the
three permitted connections, with room to spare. The correct design is therefore
*not* "poll every 5 seconds" — it is **subscribe once, maintain the book in
memory from the tick stream, and sample that state every 5 seconds.** The
snapshot cadence becomes a local clock decision, entirely decoupled from any
API limit, and the recorder stops being rate-limited at all.

Streaming modes: `ltp` (8 bytes), `quote` (44 bytes, no depth), `full`
(184 bytes, with market depth). Open interest is carried on F&O quotes.

### BSE derivatives are supported, despite the docs

The market-quotes page does not mention a BFO segment, which initially looked
like it might rule Sensex out. The instrument dump settles it: **`BFO-OPT` has
4,260 contracts** and every SENSEX option is on exchange `BFO`. Absence from one
documentation page was not absence from the product — worth remembering before
concluding anything from silence in these docs.

### Two standing assumptions confirmed, from a better source

The instrument master is a broker-maintained primary source, far stronger than
the reference playbook these came from:

| Was assumed | Measured 2026-08-18 | Verdict |
|---|---|---|
| Nifty weekly expiry on **Tuesday** (A-003) | 17 of 18 Nifty expiries are Tuesdays; the one exception is a Monday | Confirmed, with a caveat |
| Sensex weekly expiry on **Thursday** (A-003) | 19 of 19 are Thursdays | Confirmed |
| Lot sizes are time-versioned, never hardcoded (A-002) | NIFTY **65**, SENSEX **20**, today | Confirmed as *today's* values only |

**The Monday Nifty expiry is the interesting one.** It is precisely why a
recorder must never compute expiry from a weekday rule. Holiday shifts move
expiries, and code that assumes "Tuesday" will silently mis-key one contract in
eighteen. Expiry comes from the instrument master, always.

## Decision

Build the Sprint 2 recorder on the **WebSocket**, not on polling. Snapshot
cadence is a local timer over in-memory state. A-008 is resolved: 5-second
snapshots are achievable, but only this way.

## What I could not verify

- **Tick delivery rate under load.** The docs specify no throttling and no
  guaranteed tick frequency. Whether 4,138 illiquid strikes actually produce
  usable updates every 5 seconds — as opposed to the liquid few doing so while
  the far wings stay stale — cannot be known without running it during market
  hours. A stale-quote marker per instrument is therefore mandatory in the
  recorder, not optional.
- **Whether the historical API serves expired *option* contracts.** Still
  documented for futures only (research note 002). Unchanged, and it is why the
  recorder exists at all.
- **Reconnection behaviour** on a dropped socket mid-session, and whether ticks
  are replayed or simply resume. Must be established by test before relying on
  the gap-free claim in Sprint 2's criteria.
- Today's lot sizes are today's. The dump is a current snapshot and says nothing
  about history — the same limitation that disqualified Kite for the backfill.
