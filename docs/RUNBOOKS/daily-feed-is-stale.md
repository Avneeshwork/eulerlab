# Runbook — the data is a day (or more) behind

**Symptom.** A backtest ends earlier than it should, the snapshot shows
yesterday's close, or the Instruments tab lists an instrument with no recent
bars. Nothing errors — stale data reads exactly like fresh data.

**Impact.** No money at risk directly. The risk is a result computed on a short
window and reported as if it covered today.

## India minute bars are behind

They need a Kite token made today. Tools → Instruments → the Kite strip: open
Zerodha's login page, sign in, paste the address it sends you to, then press
Update on the India minute bars row. `make kite-login` then `make daily-minute`
does the same from a terminal.

## Diagnose

1. Terminal → **Instruments** → the button block states what a refresh covers.
   `curl -s localhost:8000/api/data/feed/plan` gives the same list from the
   command line; it is generated from `STEPS`, so it cannot disagree with what
   actually runs.
2. `make evidence` → per-store row counts. A store that did not grow since the
   last refresh is the one to chase.

## Fix

Look at **Data coverage** on Tools → Instruments first (`make coverage` in a
terminal): every dataset, its last day, the day it should reach and the fix.

**Update all data** on the Instruments tab (`make feed` in a terminal) runs every
step in `daily_feed.STEPS`: the NSE files, the derived tables, the price panel,
the paper books, then the other markets and the US panel. It downloads only what
is missing and uploads only what B2 lacks. Each step reports "downloaded N,
already held M" and names any that failed. If `make daily` is running, the
button is disabled and says so; wait for it.

**One dataset or one group.** Every row in Data coverage has its own
**Update** button, and every group header an **Update group** button. They run
only the steps that dataset needs (hover the button to see them) and finish in
seconds to a few minutes. They do not upload; the result line says "not
mirrored yet", and Mirror to cloud uploads it.

**Mirror to cloud** skips the fetches and just uploads what is already landed
and not yet in B2. Use it when a previous refresh fetched but died before the
sync.

**Delete local copies** frees disk. The first click is a dry run: it lists the
bucket and says how many files and GB B2 already holds at the same size. The
button then reads "Delete N files (X GB)"; only that second click deletes.
Files not yet uploaded, or held at a different size, are kept. The manifests
are untouched, so deleted files are read back from B2 when needed. Same rule
as `make prune-local` (ADR-010).

All three buttons share the `feed` lock with `make daily`; while one runs, the
others are disabled and say who is running.

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
