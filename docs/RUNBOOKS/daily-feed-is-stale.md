# Runbook — the data is a day (or more) behind

**Symptom.** A backtest ends earlier than it should, the snapshot shows
yesterday's close, or the Instruments tab lists an instrument with no recent
bars. Nothing errors — stale data reads exactly like fresh data.

**Impact.** No money at risk directly. The risk is a result computed on a short
window and reported as if it covered today.

## Diagnose

1. Terminal → **Instruments** → the button block states what a refresh covers.
   `curl -s localhost:8000/api/data/feed/plan` gives the same list from the
   command line; it is generated from `STEPS`, so it cannot disagree with what
   actually runs.
2. `make evidence` → per-store row counts. A store that did not grow since the
   last refresh is the one to chase.

## Fix

**Update daily feed** on the Instruments tab. It runs eight sources in order —
NSE end-of-day, mutual fund NAVs, economic calendar, crypto gap, FX, news,
index levels, US bars and actions — then mirrors to B2 and rebuilds the
manifest. Roughly 3–4 minutes fetching and 8–10 mirroring; the button reports
each source separately and names any that failed.

**Mirror only** skips the fetches and just uploads what is already landed. Use
it when a previous refresh fetched but died before the sync.

Nothing local is deleted by either. Pruning is a separate, deliberate step
(ADR-010).

## If that does not work

**One source failed, the rest are fine.** The step list names it with its
error. Re-run the button — the other seven are cheap and idempotent — or run
that source's own target from `make`.

**Minute bars are still stale.** They are not in the feed and never will be: a
Kite token has to be minted through an interactive login the same day. See
`kite-login.md`, then `minute-backfill.md`.

**The run refuses to start** ("a feed run is already going"). One run at a time
is enforced. Wait for it, or check `/api/jobs/<id>` if the tab was closed.

**It looks hung on the mirror.** The mirror reports two phases and the second,
"recounting the bucket", relists the whole bucket — several minutes with no
visible movement is normal there. Uploading is the phase that should move.

## Prevention

The source list the UI shows is served from the code that runs it, so the copy
cannot promise a source that is not wired in — it did exactly that once,
promising FX before FX was a step. Failures are per-source rather than
per-run, so a dead source is visible instead of silently costing the other
seven. ADR-048 records the shape.

What still is not prevented: nothing tells you the data is stale before you use
it. Both diagnostic steps above are pull, not push.
