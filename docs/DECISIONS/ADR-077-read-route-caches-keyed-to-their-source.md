# ADR-077 — Read-route caches keyed to the file they come from

**Status:** Accepted · 2026-10-16

## Context

Timing every read route on 2026-10-16 (warm, panel loaded) found four that
repeat the same parse on every request: `/api/window` 1.1 s (two scans of 5.4M
rows), `/api/options/history` 3.2 s (30 bhavcopy zips), `/api/research/papers`
0.33 s (96 YAML files), `/api/risk/book` 65 ms (company digest and stored
reports). Until now the speed work stored nothing between requests (ARCHITECTURE,
"How the dashboard loads fast").

## Options

1. A time-to-live cache on each route: simple, but serves stale data for its lifetime.
2. A cache invalidated by the thing that changes the source: no staleness, needs a
   cheap check per request.
3. Leave them.

## Choice

Option 2. Each cache is dropped by what makes it wrong:

| Cache | Dropped when |
|---|---|
| The panel's trading days (`_Panel.days`) | the panel reloads (its file's mtime) |
| A paper (`library.load`) | its YAML's mtime or size changes; callers get a deep copy |
| Sectors and backtest summaries (`risk_routes`) | the digest's or any report's name, mtime or size changes |
| A straddle-history point (`server._HISTORY_POINTS`) | never: a landed bhavcopy is immutable. A day whose chain failed to read is not kept |
| The B2 results listing (`/api/cloud/status`) | 60 s pass, **or** this server mirrors, **or** the operator presses "List the bucket again" (`refresh=true`). The screen shows the listing's time |
| The map's live quotes (`/api/snapshot`) | 15 s pass. Only a complete answer is kept. Kite allows one quote request a second, so the five calls cannot run in parallel |

Amended the same day at the operator's request: the B2 listing and the live
quotes were first left uncached. The listing is cached only because a mirror
from this server drops it, so the screen never shows the state from before its
own push; a push from another machine can be up to 60 s behind, and the listing
time says so.

## Why

The four file-backed caches cost one `stat` per request and cannot serve a
value older than their source. The two network-backed ones are bounded in age
(60 s, 15 s) and show that age. Every cached output was checked equal to the uncached one.

## Cost if wrong

A source changed without changing mtime or size (a same-size rewrite inside one
mtime tick) would be served stale until the next change or a restart. A landed
bhavcopy rewritten in place breaks the immutability rule, and the history would
not see it. A push from another machine is visible up to 60 s late; the map's
prices can be up to 15 s old, each with its true quote time.
