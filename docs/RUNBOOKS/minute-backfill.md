# Runbook — `make ingest-minute` problems

**What it does.** Downloads 1-minute candles from Kite for the symbols in
`config/universe_top250.txt`, into `data/landing/kite_minute/`. Resumable: it
reads its own manifest and fetches only what is missing, so re-running after any
failure is always safe and never re-downloads.

---

## It stopped partway through with a traceback

**Symptom (seen 2026-08-18).** The run died after 41 of 240 symbols with:

```
http.client.IncompleteRead: IncompleteRead(808834 bytes read, 98364 more expected)
```

**Diagnosis.** A truncated HTTP response. `IncompleteRead` is an
`http.client.HTTPException` — it is *not* an `HTTPError` and *not* a
`URLError`, so the original code, which caught only `HTTPError`, let it
propagate past the per-chunk handler and abort the entire run.

**Fix (already applied).** Every transport failure is now converted to
`KiteError` and retried up to four times with jittered backoff, and the runner
catches unexpected exceptions per chunk as well. One bad packet costs one chunk,
never the job.

**If it happens again:** just re-run. The manifest means it resumes from where
it stopped, and the earlier work is untouched.

```bash
make ingest-minute
```

**The general lesson, worth remembering elsewhere:** a long unattended job must
treat *any* exception from a network call as a per-item failure. Catching only
the exceptions you thought of is how a five-hour job dies at minute forty.

---

## "No access token. Run `make kite-login` first."

Kite tokens expire at 06:00 IST daily. Run `make kite-login`, then re-run. One
login covers an overnight backfill.

---

## A symbol appears in `unresolved.jsonl`

Two very different causes, and the file records the reason for each:

**"not in Kite's current instrument list"** — Kite only lists instruments that
exist *today*. Usually this is a **rename**, not a delisting. Observed on
2026-08-18: `ZOMATO` → `ETERNAL`, `GMRINFRA` → `GMRAIRPORT`, `IBULHSGFIN` →
`SAMMAANCAP`, `TATAMOTORS` → `TMPV`, `PEL` → `PPLPHARMA`, `SWANENERGY` →
`SWANCORP`, `HBLPOWER` → `HBLENGINE`.

The data is not lost; we asked under the wrong name. The fix is the security
master's symbol-change map (Sprint 3), after which those symbols re-resolve and
a plain re-run fetches them.

**This is the whole reason the file exists.** Had these been skipped silently,
five years of minute data would be missing Tata Motors and Zomato with no error
anywhere, and every backtest built on it would be quietly wrong.

**A `<date>: http ...` reason** — a genuine fetch failure for one chunk.
Re-run; only the missing chunks are retried.

---

## How long should it take?

240 symbols x 31 chunks (60 days each) = ~7,440 requests at 3/sec ≈ **42 minutes**.
Kite's limit of 60 days per request is measured, not documented — asking for 61
returns `400 interval exceeds max limit: 60 days`.

---

## Prevention

`--limit 2` runs two symbols end to end in seconds. Worth doing after any change
to the downloader, before committing to a 40-minute run.
