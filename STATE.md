# STATE — where this project is right now

**Sprint:** 1 — data foundation (EOD, minute, OI, fundamentals)
**Status:** IN PROGRESS
**Next:** Sprint 3 — security master

*Last updated: 2026-08-18 20:30 IST. One page, always current. If it is not
written here or in `TASKS.md`, it did not happen.*

---

## Datasets — what actually exists

| Dataset | State | Where |
|---|---|---|
| NSE EOD bhavcopy (cash + F&O) | **COMPLETE** — 5,736 files, 2015-01-01 → 2026-08-17 | `data/landing/nse/{cm,fo}/`, mirrored to B2 |
| Participant-wise F&O OI | **COMPLETE** — 1,632 weekdays, 2020-01-01 → today | `data/landing/nse/participant_oi/` |
| Kite 1-minute bars | **COMPLETE** — 12,755 chunks, 411 symbols, 173M bars, 5 years | `data/landing/kite_minute/` |
| screener.in fundamentals | **IN PROGRESS** — ~184 of 2,702 companies | `data/landing/fundamentals/` |
| Options chains / tick data | **NOT STARTED** — deferred by the operator | — |

Local disk holds a working subset only; the full copy lives in B2 bucket
`eulerdata`. Files are pruned locally after B2 confirms them (ADR-010) and can
be pulled back with `make restore-local`.

## Architecture

`docs/ARCHITECTURE.md` — diagrams of the fetch/landing/cloud pipeline, the
atomic write path, the prune/restore loop, and the module map. Reflects what is
built, not what is planned.

## Commands that work today

```bash
make verify                      # five gates, the only check that matters
make daily                       # refresh EOD + OI + fundamentals, sync, prune
make ingest-eod FROM=2015-01-01  # bhavcopy backfill (idempotent, resumable)
make ingest-oi FROM=2020-01-01   # participant-wise OI
make ingest-minute               # Kite 1-minute bars
make ingest-fundamentals         # screener.in fundamentals
make kite-login                  # Kite token (expires 06:00 IST daily)
make sync-cloud / prune-local / restore-local / check-landing
```

## Running background jobs (2026-08-18 evening)

- `fundamentals.backfill` — ~2,700 companies, ~110 min total
- `sync_cloud` — mirroring to B2
- `disk_watchdog.sh` (in the scratchpad) — syncs and prunes when disk drops
  below 3 GB, halts downloaders below 1 GB. Not yet part of the repo.

## Known issues and open questions

- **Disk is the binding constraint.** The machine has ~5 GB free of 228 GB;
  most of that is unrelated to this project. A backfill crashed on ENOSPC once
  already. The watchdog mitigates but does not solve it.
- **10 minute-backfill symbols unresolved** — renames and demergers
  (ZOMATO→ETERNAL, TATAMOTORS→TMPV). Deliberately not fixed by a hand-written
  alias map, because a demerger splits one history into two and an alias cannot
  express that. Sprint 3 handles it. See `docs/STUBS.md` S-005.
- **Three datasets are collected against site terms**, knowingly: NSE
  (ADR-006), Trendlyne (ADR-009, not yet built), screener.in (ADR-011). Each is
  a recorded operator decision with the clause quoted, not an oversight.
- **No consensus/forecast data exists** for Indian macro or earnings, so
  "surprise" is not computable. Flagged in research notes 004 and 005; may be
  the binding constraint on event-driven strategies.
- **Credentials leaked into git history and were rotated** (2026-08-18). Live
  exposure closed; a history rewrite is still an open question.
- **Most market-structure facts remain unverified** — see `docs/ASSUMPTIONS.md`.

## Money

| Cost | Amount | Status |
|---|---|---|
| Zerodha Kite Connect | ₹500/mo | Active |
| Backblaze B2 | under ₹100/mo | Active, bucket `eulerdata` |
| Mumbai VPS | ₹500–900/mo | Deferred — only the options recorder needs it |

**Run rate: ~₹600/mo.**
