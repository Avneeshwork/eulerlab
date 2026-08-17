# Kickoff — what to paste into the IDE

---

## Step 1 — Setup (15 min, once)

```bash
mkdir quantlab && cd quantlab && git init
curl -LsSf https://astral.sh/uv/install.sh | sh     # Python package manager
```

Copy these three files into the folder:
- `AI_BUILD_PLAN.md` → `docs/AI_BUILD_PLAN.md`
- `quant_platform_playbook.md` → `docs/quant_platform_playbook.md`
- `CLAUDE.md` → `CLAUDE.md` (repo root — this is the important one)

Then open Claude Code in that folder.

---

## Step 2 — Paste this prompt

> Read `CLAUDE.md` and `docs/AI_BUILD_PLAN.md`. We are starting Sprint 0.
>
> Sprint 0 goal: build the scaffolding so that every future sprint is verifiable in two minutes. Nothing trades. No market data yet.
>
> Deliver:
> 1. `STATE.md` and `TASKS.md`, seeded with sprints 0–14 from the build plan
> 2. `Makefile` with targets: `verify`, `test`, `lint`, `types`, `docs-check`, `state`
> 3. `pyproject.toml` with uv, ruff, mypy strict, pytest, pre-commit hooks installed
> 4. Full `docs/` tree — every template filled with a real worked example, not blank
> 5. `.github/workflows/ci.yml` running lint + types + tests + docs-check
> 6. `docs/READING/index.md` with my MUST-read list for sprints 1–4
> 7. One trivial module plus its test, so `make verify` proves the harness works end to end
> 8. `docs/SPRINT_00_REVIEW.md`
> 9. `docs/COMPLIANCE_DEFERRED.md` with the deferred items and their trigger points
>
> Keep the three compliance stubs from the build plan (algo_id field, OPS governor config key, static_ip config placeholder) — just as config and schema placeholders, nothing implemented.
>
> Before writing anything: give me your 5-bullet plan and wait for my go.

---

## Step 3 — Verify Sprint 0 (2 min)

```bash
make verify
```

You should see a table like:

```
CHECK            RESULT   DETAIL
lint             PASS     0 issues
types            PASS     0 errors in 3 files
tests            PASS     4 passed
docs-check       PASS     all src changes have docs
state            OK       Sprint 0 complete, next: Sprint 1
```

Then read `docs/SPRINT_00_REVIEW.md`, answer any decision questions, and say **"next sprint"**.

**If anything is red:** paste the output back. Don't move on. A broken harness in Sprint 0 poisons every sprint after it.

---

## Sprint acceptance criteria — the next three

Copy these into `TASKS.md`. These are the definitions of done, so neither of us can drift.

### Sprint 0 — Scaffolding
- [ ] `make verify` runs and prints a green table
- [ ] CI passes on a pushed branch
- [ ] Committing a change to `src/` without a doc change makes `docs-check` fail (test this deliberately)
- [ ] `STATE.md` accurately describes reality in under one page
- [ ] `docs/READING/index.md` has my MUST list for sprints 1–4
- [ ] `.gitignore` covers `data/`, `.env`, `__pycache__`, `.venv`

### Sprint 1 — NSE EOD ingest
- [ ] `make ingest-eod FROM=2015-01-01` downloads bhavcopy + F&O bhavcopy into `data/landing/`, gzipped, one file per day, never modified after write
- [ ] Re-running downloads **zero** files and says so
- [ ] Interrupt it with Ctrl-C mid-run, restart, it resumes correctly
- [ ] Respects NSE rate limits; retries with backoff; never hammers the site
- [ ] Prints a summary: date range, files fetched, files skipped, rows parsed, holidays detected
- [ ] `docs/RESEARCH/001-nse-archive-schemas.md` documents each file's columns with the URL and fetch date
- [ ] A missing-day report distinguishes "market holiday" from "download failed"

### Sprint 2 — Options chain recorder (do this early; lost days are lost forever)
- [ ] Runs on the VPS under systemd, restarts automatically on crash
- [ ] Snapshots Nifty (NSE) and Sensex (BSE) full option chains every 5 seconds, 09:15–15:30 IST, trading days only
- [ ] Writes Parquet, partitioned by date, one file per day, with **both** the exchange timestamp and my receive timestamp on every row
- [ ] Survives a network drop and resumes without gaps in the file
- [ ] Disk usage projected and logged (estimate ~50–200 MB/day; confirm with real numbers)
- [ ] `make recorder-status` shows: last snapshot time, rows today, gaps today, disk free
- [ ] A daily heartbeat to your phone (Telegram bot is free) so you notice within a day if it dies
- [ ] Documented in `docs/RUNBOOKS/recorder.md`: how to restart, where files go, how to check for gaps

---

## What your first month looks like

| Week | Sprints | Your total time |
|---|---|---|
| 1 | 0, 1 | ~30 min |
| 2 | 2, 3 | ~40 min (plus VPS setup) |
| 3 | 4, 5 | ~40 min (plus ~1 hr MUST reading on lookahead bias) |
| 4 | 6, 7 | ~40 min |

End of month one you have: clean India EOD history from 2015, a security master that knows what every contract's lot size was on any past date, an options recorder building an asset you can't buy, a lookahead firewall with tests that try to break it, and a quality engine. Total spend: about ₹1,000/month.

No strategy yet. That's deliberate — the strategy work in Sprints 8–14 is only worth doing on top of infrastructure that can't lie to you.

---

## One thing to decide before Sprint 2

The recorder needs a live data source. Cheapest options:

| Option | Cost | Trade-off |
|---|---|---|
| **Dhan API** | Free | Free tier limits; verify chain snapshot rate is allowed |
| **Zerodha Kite Connect** | ₹500/mo | Most reliable, best docs, widely used |
| Both | ₹500/mo | Two sources = cross-reconciliation, the best data-bug detector there is |

Recommendation: **both**, if you already have accounts. The second source costs nothing extra and catches vendor errors that would otherwise show up later as fake alpha. I'll ask you this in the Sprint 1 review.
