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
split about 200s of fetching against 580s of mirroring, so **the mirror, not
the fetching, was what a refresh cost.**

Where that went was measured rather than assumed, because the first guess here
was wrong — it blamed the manifest rebuild, which is the visibly slow-looking
step. Counted properly, the mirror listed the bucket **twenty-five times**:

| listing group | count | time | keys |
| --- | --- | --- | --- |
| whole prefix, for the bhavcopy diff | 1 | 103.2s | 142,007 |
| per tree, `sync_directory` | 12 | 128.6s | 134,600 |
| per tree again, `manifest.build` | 12 | 81.8s | 104,060 |
| | **25** | **313.6s** | |

Every one of those is a subset of the first. 314 of the mirror's 578 seconds
was asking B2 again for keys it had already returned. An earlier revision of
this ADR called the sharing "not worth rushing for 20%"; that estimate was made
without counting, and the real figure is 54%.

So one enumeration is taken per run and every consumer slices it:
`plan_sync`, `sync` and `sync_directory` accept a `remote_sizes` already in
hand, and `landing_reader.prime_listing` fills the census cache from the same
result through the same `_matches` test the network path uses — so a primed
answer and a fetched one cannot disagree. Sweeps after the first still list,
because a tree that appeared mid-run is by definition absent from a listing
taken before it existed.

The one remaining enumeration is itself mostly waiting: a LIST returns 1,000
keys and the next request needs the previous one'"'"'s continuation token, so
142,000 objects is 142 strictly sequential round trips. The sub-prefixes are
independent, so `list_sizes_fanned` discovers them with one delimited request —
from the bucket, not from a list in the code, so an unremembered tree is still
walked — and enumerates them twelve at a time. Verified against the real
bucket: identical 142,007-key result, 103.7s to 47.6s.

`sync()` also uploaded serially while `sync_directory` had used a thread pool
for months — the same work against the same store at two speeds, because the
two functions were written apart. It now uses the same pool.

Measured end to end, the same button: **781s to 281s.** The mirror went 578s to
117s. The two runs are not quite like-for-like — the slow one uploaded 833
objects and the fast one 417 — so normalised per object the mirror is about 3x,
and the listing that dominated it is 6.6x.

Reviewing that change afterwards turned up three things worth naming, because
each was invisible in a passing test run.

**The fanned listing dropped loose keys past the first page.** `list_groups`
followed continuation tokens; the delimited request that picks up keys sitting
directly under the prefix did not. Every key in this bucket lives inside a
tree, so the count came out right and the bug was pure latency — until someone
drops more than a thousand objects at the root, at which point the overflow
reads as absent, the sync re-uploads it and the census undercounts. Pagination
is now one primitive, `_list_page_by_page`, so a new call site cannot forget
the loop.

**`sync()` let a read failure escape.** The re-hash guard was inside the try
and the `read_bytes` above it was not, so a file deleted between the plan and
the upload raised out of the pool and took the run with it — with the comment
beside it promising one bad object could not do that. `sync_directory` had it
right; the two were simply written apart.

**Priming used a listing taken before the uploads.** The census counts local
and remote together, so a file uploaded this run is still counted — it is on
disk. That holds only until something prunes local files between the sync and
the census, which is precisely what `make daily` does. It survives today
because `sync-cloud`, `prune-local` and `manifest` are three processes and the
cache never crosses between them. Resting a correctness guarantee on that is
not a design, so `SyncResult` and `TreeSyncResult` now report the keys they
actually wrote and the prime takes the union.

The imbalance made the progress display wrong before it made it slow: a single
"mirroring to B2" message sat unchanged for nine minutes and read as hung. The
mirror reports two phases — uploading, then recounting — for that reason alone.
