# Backblaze B2 daily transaction cap

## Symptom

Any B2 download fails with:

```
botocore.errorfactory.AccessDenied: An error occurred (AccessDenied) when
calling the GetObject operation: Cannot download file, download bandwidth or
transaction (Class B) cap exceeded.
```

Listing still works, which makes it look like a permissions problem on
specific objects. It is not — `list_objects_v2` is a Class C transaction and
has its own separate allowance.

## Diagnosis

B2's free tier allows **2,500 Class B (download) transactions per day**.
Bandwidth is rarely the binding constraint here: the entire cash-bhavcopy
history is only 271 MB across 2,870 files, well under the 1 GB/day free
download. It is the **per-file transaction count** that runs out, because
every file is one GET.

What exhausted it on 2026-08-19: `build-factors` fetches one bhavcopy per
ex-date, 2,121 files — **85% of a full day's allowance in a single run**.
Running it twice in one session (once to build, once after fixing a join bug)
went over.

Check what a run will actually cost before starting it:

```bash
make build-factors
```

The first lines report `N already cached, M to download`. If `M` is more than
about 2,000, expect to use most of the day's allowance.

## Fix

**Wait for the daily reset** (B2 caps reset on a rolling 24-hour basis), then
re-run. The run is resumable and cached, so nothing already downloaded is
fetched again:

```bash
make build-factors
```

`data/derived/close_index.jsonl` holds every price already retrieved plus a
marker per processed date. A capped run stops partway and the next run picks
up exactly where it left off. Once the cache is complete, rebuilds cost **zero
downloads**.

Do not delete `data/derived/close_index.jsonl` to "start clean" — that throws
away the one expensive thing in this pipeline and forces the whole 2,121-file
pull again.

## Prevention

- **Never write a loop that re-downloads what it already has.** The cache in
  `eulerlab.corp_actions.prices.build_close_index` exists for this reason and
  is checked on every run.
- **Filter the file list before fetching, not after.** Only ex-dates need a
  bhavcopy for adjustment factors: 2,121 files instead of 2,870, and only
  dividends and rights need prices at all — bonuses and splits are pure ratio
  arithmetic.
- If a future job genuinely needs the full history repeatedly, restore the
  files locally once with `make restore-local` and read from disk rather than
  paying a transaction per file per run.
- Raising the cap is a paid change on the Caps & Alerts page. Given the run
  rate is about ₹600/mo and the cache makes this a one-time cost, there is no
  measured need for it — see `CLAUDE.md` on cost discipline.
