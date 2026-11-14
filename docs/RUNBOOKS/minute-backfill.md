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

**Do not hand-write an alias map to "fix" these.** That was attempted on
2026-08-18 and produced a wrong answer within minutes: `PEL` was matched to
`PPLPHARMA`, but Piramal Enterprises *demerged* — the dump contains both
`PPLPHARMA` and `PIRAMALFIN`. `TATAMOTORS` is the same shape: only `TMPV`
exists in the dump, and the commercial-vehicles half is not under any obvious
name.

A demerger splits one company's history into two. A one-to-one alias cannot
represent that, and forcing one would silently attach the wrong company's five
years of minute bars to the old symbol — an error that no test would catch,
because the data would look perfectly well-formed.

The correct fix is the security master (Sprint 3), which models corporate
actions properly. Until then these stay unresolved and visible.

**This is the whole reason the file exists.** Had these been skipped silently,
five years of minute data would be missing Tata Motors and Zomato with no error
anywhere, and every backtest built on it would be quietly wrong.

**A `<date>: http ...` reason** — a genuine fetch failure for one chunk.
Re-run; only the missing chunks are retried.

---

## It is crawling, and `unresolved.jsonl` is full of URLError

**Symptom (seen 2026-08-18).** Throughput collapsed to ~0.1 chunks/sec against a
3/sec target, with hundreds of
`URLError: [Errno 8] nodename nor servname provided, or not known`.

**Diagnosis.** That is **DNS failing locally**, not Kite refusing anything. DNS
tested clean moments later, so it is transient flakiness on the machine or its
network.

**Why it hurt so much.** The retry policy was patient — 4 attempts backing off
up to 20s — so each transient failure cost ~14 seconds of sleeping. 307 failures
burned roughly 70 minutes doing nothing.

**Fix (applied).** The policy is now deliberately impatient: 3 attempts, 1s
base, 5s cap. A failed chunk is *not lost* — it is simply absent from the
manifest, so the next run fetches it. Waiting is therefore expensive and
pointless. Throughput went from 0.11/sec to 1.20/sec.

**The general lesson:** retry patience should scale with how expensive a retry
is to replace. When the work is idempotent and resumable, failing fast and
sweeping up later beats waiting.

## Why the universe is a union, not a snapshot

`config/universe_top250_union.txt` is the union of the top 250 by turnover
sampled at each year-end from 2021 to 2026 — 444 symbols, not 250.

A single snapshot is survivorship-biased whichever date you pick. Measured:
only **168 of 250** names are in both the Sept-2024 and Aug-2026 lists. Using
today's list gives five years of history for today's winners; using an old one
misses everything that has since become liquid (`ETERNAL`, `SWIGGY`, `TMPV`).

The union costs 1.8x the download and removes the choice entirely.

## How long should it take?

240 symbols x 31 chunks (60 days each) = ~7,440 requests at 3/sec ≈ **42 minutes**.
Kite's limit of 60 days per request is measured, not documented — asking for 61
returns `400 interval exceeds max limit: 60 days`.

---

## Prevention

`--limit 2` runs two symbols end to end in seconds. Worth doing after any change
to the downloader, before committing to a 40-minute run.

---

## Angel One: history before Kite's five years (research 193)

`make angel-history` fetches 3 Oct 2016 to 18 Aug 2021 for the union, the
three indices and `config/angel_delisted_tokens.csv`, into
`data/landing/angel_minute_history`. Newest month first, so a stopped run
leaves every name with its latest years. Re-run to resume. About 50,000
requests at one a second, so about 14 hours. Log: whatever you redirect it to
(the 2026-11-13 run wrote `data/logs/angel_history.log`).

**"truncated" failures.** Angel returns at most 8,000 candles and silently
drops the earliest. The fetcher refuses such a reply. If one appears, the
month was split wrongly: lower `MONTH_SESSIONS`.

**Do not merge this tree into `kite_minute`.** Kite and Angel adjust old
prices differently (RELIANCE 2021-08-20 close: Kite 1,020.00, Angel 1,074.13).
Joining them unadjusted puts a false jump at 19 Aug 2021.

## A session is short in `kite_minute` after an Angel fill

Find it: count one-day files per date in the manifest. The daily fill now
re-asks short sessions of the last 14 days by itself. For an older one:

```bash
make angel-minute FROM=2026-11-09
```

Do not pass a range that spans an NSE holiday: `angel-minute` asks Angel for
every weekday and lands zero-row files for the holiday.

## The Angel backfill stopped (rate limit, login, crash)

`make angel-backfill-supervise ACTION=install` loads a launchd agent
(`tools/com.eulerlab.angel-backfill.plist`) that runs
`tools/angel_backfill_supervised.sh`: one resumable history pass, B2
upload-and-delete of the minute trees every 30 minutes and at the end, and
exit 1 unless the pass fetched nothing new and failed nothing. launchd
restarts it five minutes after any non-zero exit, so a limit or a killed
process costs five minutes, not the night. It waits for a hand-started run to
end before fetching. Log: `data/logs/angel_backfill.log`, each pass's detail in
`data/logs/angel_history_pass.log`. `ACTION=status` shows it; `ACTION=uninstall`
stops it.

**Start date (operator, 2026-11-14).** The backfill stops at 1 Nov 2018, eight
years back: "leave Oct 2016 to Oct 2018". Angel has stocks to 3 Oct 2016 if
that is ever wanted: `make angel-history FROM=2016-10-01`. The months already
landed (Feb 2020 and later, plus a few from earlier runs) are kept.
