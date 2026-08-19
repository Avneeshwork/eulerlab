# Sprint 1 — Data foundation

**Status:** COMPLETE
**Branch:** sprint-01-nse-eod-ingest   **Commits:** 20+

Four datasets landed, verified, and mirrored to cloud. This sprint grew well
beyond its original scope (NSE EOD ingest) because the operator added minute
bars, positioning data and fundamentals as it went.

---

## What now works (plain English, no jargon)

- **Eleven years of daily prices.** Every trading day's cash and F&O bhavcopy
  since January 2015 — 5,736 files, complete through 2026-08-17.
- **Six years of positioning data.** Who actually holds the F&O open interest,
  split by FII / DII / Pro / Client, daily since 2020. 1,632 days. This is the
  most valuable free dataset found: positioning *causes* price movement rather
  than summarising it afterwards.
- **Five years of minute bars.** 173 million rows across 411 symbols, on a
  survivorship-free universe built from our own turnover data rather than a
  published index list.
- **Fundamentals for 2,352 companies.** Quarterly results, P&L, balance sheet,
  cash flow, ratios, shareholding, plus sector hierarchy, index membership and
  valuation ratios.
- **All of it in the cloud.** 22,478 objects, 4.32 GB in Backblaze B2. Local
  disk holds 0.01 GB — files are pruned once B2 confirms them and can be pulled
  back with `make restore-local`.
- **`make daily`** refreshes everything, syncs, and prunes. Safe to schedule:
  every step is idempotent, so a missed day self-heals.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: 5 of 5 green
make check-landing   # expect: all checksums match, pruned files confirmed in B2
```

Expected: `verify OK: 5 of 5 checks green`, and check-landing reporting every
on-disk file matching its checksum with the rest confirmed present in B2.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| `Order` model with `algo_id` | Reserves the field before the OMS exists | 19 |
| `max_orders_per_second: 5` | Config key, nothing enforces it yet | 19 |
| `static_ip: null` | Needs a VPS and broker registration | 29 |
| 10 minute-bar symbols unresolved | Renames and demergers; deliberately not hand-mapped | 3 |

## What I could not verify

- **Kite's tick frequency (A-013).** Unknown until a live session runs. Matters
  for the deferred options recorder, not for anything built here.
- **Most market-structure facts.** Lot sizes, settlement rules, the SEBI OPS
  threshold — still from the reference playbook, not primary circulars. See
  `docs/ASSUMPTIONS.md`.
- **Whether `corporates-financial-results` reaches back beyond 2020.** Only
  2020 and the current quarter were tested.

## Mistakes made this sprint, and what changed because of them

Recorded because the fixes are the durable part.

1. **I leaked your credentials.** `git add -A` swept an edited `.env.example`
   — a tracked file — into a commit and pushed it. Zerodha and Telegram keys
   were exposed and had to be rotated. Now `tests/test_no_secrets.py` fails the
   build if any value in that file is non-empty.
2. **The docs gate was mis-reading its own input since Sprint 0.** `.strip()`
   on `git status --porcelain` output ate the leading space of the first line,
   so the first unstaged file's path lost a character and stopped counting as
   documentation. Found by audit, not by failure.
3. **Fundamentals had zero objects in the bucket** while looking healthy
   locally, because `sync_cloud` mirrored a hardcoded list of trees. Worse,
   `--dry-run` returned before the tree loop ran and reported "would upload: 0".
   A check that reassures you while the thing it checks is broken is worse than
   no check. Trees are now discovered, not listed.
4. **A backfill died on a truncated HTTP response** after 41 of 240 symbols,
   because only `HTTPError` was caught. Now every transport failure is a
   per-chunk failure, never a job-killer.
5. **The disk filled and crashed a backfill.** Led to `prune-local`,
   `restore-local` and `sync-until-complete` — pruning is only safe if
   restoring exists, and it did not until this forced it.
6. **I nearly shipped a wrong symbol map.** Matching `PEL` to `PPLPHARMA`
   looked right; Piramal actually demerged into two entities. A one-to-one
   alias cannot express that, and no test would have caught the wrong data.

## Decisions you made

| Decision | Recorded in |
|---|---|
| Proceed against NSE's terms | ADR-006 |
| NSE for history, Kite for live | ADR-005 |
| Backblaze B2 as the mirror | ADR-007 |
| Universe from our own turnover, not an index list | ADR-008 |
| Collect Trendlyne's FII/DII archive | ADR-009 (not built) |
| Prune local after cloud confirmation | ADR-010 |
| Scrape screener.in fundamentals | ADR-011 |
| Defer the options recorder | three times; TASKS.md |

## Reading added for you

- **Lookahead and survivorship bias** (MUST, 60 min) — now due before Sprint 4.
  This sprint produced three concrete examples of survivorship bias in the
  wild: Kite's current-only instrument list, the index-membership snapshot, and
  the universe-selection window. Worth reading before you approve the firewall.

## Next sprint

**Sprint 3 — security master.** Time-versioned instruments, a symbol-change map
that distinguishes renames from demergers, and a trading calendar built from
evidence. It is the direct fix for the unresolved-symbol problem that has now
affected three separate datasets.
