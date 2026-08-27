# ADR-048 — A button refreshes every source that needs no login

**Status:** ACCEPTED · 2026-08-27

**Context.** Refreshing the cloud database was a sequence of `make` targets run
by hand, in an order nobody had written down, followed by a sync. The order
matters — the mirror has to run last or it carries yesterday's data — and the
targets fail independently, so a half-finished refresh looked exactly like a
finished one. The operator wanted this as a button.

One source cannot be behind a button. Kite minute bars need an access token
minted through an interactive login **that same day** (see
`RUNBOOKS/kite-login.md`); a browser button cannot obtain one. So the honest
scope of a button is "every source that authenticates with a stored key or no
key at all", which is eight of the nine.

**Options.**

1. **One target that runs everything.** Puts minute bars in a list the button
   cannot honour — either it fails every run, or it is silently skipped and the
   operator believes minute data refreshed when it did not.
2. **A button per source.** Eight buttons and the ordering constraint moves into
   the operator's head, which is where it already was.
3. **One step list in code, run in order, each step reported separately.**

**Choice.** Option 3. `ingest/daily_feed.py` holds `STEPS` — eight named
sources — and `refresh()` runs them in order, catches per step, and mirrors
last. Every step reports its own ok/failed and duration.

Two things follow from the failure model. A dead source records and the run
continues, because one source being down should not cost the other seven. And
the mirror runs after the fetches, carrying whatever landed rather than
whatever landed last time.

**The exclusion is served, not written.** `/api/data/feed/plan` returns the
source list and the minute-bar exclusion from the same tuple that `refresh()`
iterates, and the UI renders that. The first version had the list typed into
the component; it promised FX while `STEPS` did not include FX. Prose about
what the code does, kept next to the code but not derived from it, drifts —
this is the same defect as the three copies of the asset-class list, and the
same fix.

**Cost if wrong.** Small. A ninth source is a line in `STEPS`; a source that
should not run is `only=`. Revisit if a source ever needs to run *between* the
fetches and the mirror, which the current shape has no place for.

**Consequences.**

The first full run took 14 minutes on a 30-day US window and was cut to 7 days,
which is enough to cover a long weekend plus a late correction. The run then
splits about 200s of fetching against 580s of mirroring — the mirror is now the
dominant cost, and most of that is the manifest rebuild relisting the bucket
rather than the 833 objects uploaded.

That imbalance made the progress display wrong before it made it slow: a single
"mirroring to B2" message sat unchanged for nine minutes and read as hung. The
mirror reports two phases — uploading, then recounting — for that reason alone.
