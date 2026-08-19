# ADR-015 — The download timestamp is not the knowledge time

**Date:** 2026-08-19 · **Sprint:** 4 · **Status:** accepted

**Context.** Every manifest row carries a field named `knowledge_time`. It
holds the moment *we* downloaded the file. Sprint 4 wired the bitemporal store
to real manifests and measured what that field actually contains: the median
gap between a file's trade date and our download of it is **1,820 days**, and
the earliest download timestamp across all 7,378 NSE files is 2026-08-18.
Filtering a backtest on that field returns an empty frame for all eleven years
of history — and the tempting fix, loosening the filter, is a leak.

**Options.** (a) Keep one field and treat the download time as knowledge time.
(b) Rewrite the manifests so the field means publication time. (c) Three
separate times — `event_time`, `knowledge_time`, `receipt_time` — with
knowledge derived from the trade date and the download time kept for auditing.

**Choice.** (c), plus a `Vintage` marking whether content is point-in-time.

**Why.** (a) is unusable, and its failure mode is an empty result that invites
someone to disable the guard. (b) violates the immutability of the landing
zone: the manifests are append-only evidence of what we did, and editing them
to correct a label is a worse fault than the label. (c) leaves the record
untouched, reads the misnamed field as what it has always held, and derives the
backtest's clock from the trade date instead. The derivation needed an
assumed publication hour (A-014), so the loader raises when a file appears to
have been fetched before it could have existed — that guard fired immediately
on real data and exposed a wrong hour for participant OI, which was then set
from the one same-day capture we have rather than guessed again.

The `Vintage` flag exists because timing and content are separable and only one
of them is recoverable. We can say honestly when a 2015 bhavcopy became
knowable. We cannot say whether NSE later corrected it, because we hold only
what the archive serves today. `FINAL` means exactly that; `LIVE` is reserved
for same-day captures. There are currently **4 of those out of 7,378**, and
that ratio is a property of the dataset the operator should see, not a detail
to bury.

**Cost if wrong.** If the assumed hour is too late, backtests are slightly
pessimistic about intraday timing — daily strategies are unaffected, since the
data is knowable the same evening either way. If it is too early, that is a
real leak, which is why the value is chosen late and why the guard exists.
