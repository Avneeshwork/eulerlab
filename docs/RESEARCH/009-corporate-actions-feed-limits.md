# 009 — Corporate-actions feed: date-range limits and history depth

**Sprint:** 5 · **Date:** 2026-08-19 · **Confidence:** high (endpoint queried
directly with several date windows)

## Question

Research note 008 found the endpoint but left two things unverified: how far
back it reaches, and whether requesting a wide date range silently truncates
or paginates. Both had to be answered before designing the backfill.

## Findings

**Date parameters are honoured, not ignored.** A request for `2020-01-01` to
`2020-12-31` returned only rows with `exDate` inside that window (min
2020-01-06, max 2020-12-31). This is unlike the FII/DII flow feed surveyed in
research note 004, which silently ignores its date parameters — worth naming
so the same mistake is not repeated here without checking.

**No pagination limit was hit.** A single request for the full `2015-01-01`
to `2026-08-19` span returned 25,644 rows, 7.9 MB, in one response. The
backfill therefore lands one file per **year**, not one per day — 12 requests
for the whole history, run and confirmed in this session.

**The feed reaches back further than our price history.** A `2005-01-01` to
`2010-12-31` probe returned 8,430 rows. Nothing before 2015 is useful — there
is no bhavcopy to adjust — so the backfill starts at 2015 regardless.

**`caBroadcastDate` (the field that would carry an announcement date) was
null on all 25,644 rows probed.** `exDate` is the earliest date available
anywhere in the feed. See ADR-016 for the consequence: knowledge_time is
conservatively the ex-date itself.

## Decision

Backfill one JSON file per year, 2015 through the current year, using the
existing `Landing`/`Fetcher` machinery unchanged. Implemented and run this
session: 12 files landed, 25,713 rows parsed (a few more than the earlier
probe, since NSE added rows between the probe and the run — the feed is live,
not a fixed archive).

## What I could not verify

- Whether a request wider than 2015-2026 (e.g. spanning >15 years) would
  eventually hit a limit. Not needed at current scope.
- Whether `recDate` (record date) is ever earlier than `exDate` for any row —
  if it were, it would be a candidate for a tighter knowledge_time than
  ADR-016 chose. Not checked; ex-date is safe regardless.
