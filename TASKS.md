# TASKS — the ledger

Every task, its status, and the command that proves it. Statuses:
**TODO** · **DOING** · **DONE** · **BLOCKED** · **KILLED**

Sprints 0–14 are seeded from `docs/AI_BUILD_PLAN.md` §6 and
`docs/sprint_01_kickoff.md`. Sprints 15+ are planned three ahead, per the build
plan — they are listed here as scope only, not as tasks.

---

## Sprint 0 — Scaffolding · **COMPLETE**

Verify: `make verify`

| ID | Task | Status |
|---|---|---|
| T-001 | `pyproject.toml` + uv lockfile, ruff, mypy strict, pytest, pre-commit | DONE |
| T-002 | `Makefile`: `verify` `test` `lint` `fmt` `types` `docs-check` `state` | DONE |
| T-003 | `tools/verify.py` — prints the green/red table, non-zero exit on failure | DONE |
| T-004 | `tools/docs_check.py` — src/ change without docs fails | DONE |
| T-005 | `tools/state.py` — STATE.md is machine-readable | DONE |
| T-006 | `STATE.md`, `TASKS.md` seeded through sprint 14 | DONE |
| T-007 | `docs/` tree, every type present with a worked example | DONE |
| T-008 | `.github/workflows/ci.yml` — lint, types, tests, docs-check | DONE |
| T-009 | `docs/READING/index.md` — MUST list for sprints 1–4 | DONE |
| T-010 | Compliance stubs: `algo_id`, `max_orders_per_second`, `static_ip` | DONE |
| T-011 | `docs/SPRINT_00_REVIEW.md` | DONE |
| T-012 | `.gitignore` covers `data/`, `.env`, `__pycache__`, `.venv` | DONE |

**Acceptance criteria** (from the kickoff doc):

- [x] `make verify` runs and prints a green table
- [x] **CI passes on a pushed branch** — run 32088448395, all five gates green in 13s
- [x] A `src/` change with no doc change makes `docs-check` fail — tested
      deliberately, and permanently in `tests/test_docs_check.py`
- [x] `STATE.md` describes reality in under one page
- [x] `docs/READING/index.md` has the MUST list for sprints 1–4
- [x] `.gitignore` covers `data/`, `.env`, `__pycache__`, `.venv`

---

## Sprint 1 — NSE EOD ingest · **BLOCKED** (code done; source licence needed)

Verify: `make ingest-eod FROM=2015-01-01`, then run it again — second run must
download nothing.

**Decided 2026-08-18:** history starts at **2015-01-01** (~11 years). Cheap to
extend later — the downloader is idempotent, so widening the range re-fetches
only the new days.

| ID | Task | Status |
|---|---|---|
| T-101 | Research NSE archive URLs + schemas → `docs/RESEARCH/002-nse-eod-sources-and-schemas.md` | DONE |
| T-109 | Source the trading calendar (holiday vs failed download) — cannot be derived from file absence | TODO — blocks T-107 |
| T-110 | Handle both bhavcopy formats: legacy (2015→mid-2024) and UDiFF (2024-01→), probing rather than hardcoding the cutover | DONE |
| T-111 | Cross-validate the two schemas on the Jan–Jul 2024 overlap window where both formats exist | TODO |
| T-112 | Review NSE's terms on automated archive access before the first full backfill (A-010) | DONE — **terms prohibit it.** Backfill not run |
| T-113 | **Decide a licensed history source** — NSE Data & Analytics portal, written NSE permission, or Kite + a historical instrument master | BLOCKED — operator decision, review Q1 |
| T-114 | Solve the historical instrument-master problem if Kite becomes the history source (its instrument dump is a current snapshot) | TODO — only if T-113 picks Kite |
| T-102 | Bhavcopy + F&O bhavcopy downloader into `data/landing/`, gzipped, one file per day | DONE |
| T-103 | Idempotency: re-run downloads zero files and says so | DONE — proven on real data, 20.6s then 1.3s |
| T-104 | Resumability: Ctrl-C mid-run, restart, resumes correctly | DONE — proven against SIGKILL, stronger than Ctrl-C |
| T-105 | Rate limiting + retry with backoff | DONE |
| T-106 | Summary output: date range, fetched, skipped, rows parsed, holidays | DONE |
| T-107 | Missing-day report distinguishing "market holiday" from "download failed" | DONE — three honest states, never guesses |
| T-108 | Landing zone is immutable — files never modified after write, enforced by test | DONE — `make check-landing` |

---

## Sprint 2 — Options chain recorder · **TODO** (do early; lost days are lost forever)

Verify: `make recorder-status`

| ID | Task | Status |
|---|---|---|
| T-201 | **Decide the live data source** | DONE — Zerodha Kite Connect only, ₹500/mo (ADR-004) |
| T-211 | **Verify Kite permits a 5s full-chain snapshot** against its documented rate limits — A-008 | TODO — **first task of Sprint 2, before any recorder code** |
| T-212 | Confirm Kite Connect account + API key issued | TODO — operator action, has lead time |
| T-202 | Provision a Mumbai-region VPS (~₹500–900/mo) | TODO — operator action. Decided 2026-08-18: VPS, not the laptop. A laptop that sleeps or drops wifi puts unrepairable holes in the history |
| T-203 | Snapshot Nifty (NSE) + Sensex (BSE) chains every 5s, 09:15–15:30 IST, trading days | TODO |
| T-204 | Parquet, partitioned by date, **both** exchange timestamp and receive timestamp per row | TODO |
| T-205 | systemd unit, auto-restart on crash | TODO |
| T-206 | Survives a network drop and resumes without gaps | TODO |
| T-207 | Disk usage projected and logged (estimate 50–200 MB/day; confirm with real numbers) | TODO |
| T-208 | `make recorder-status`: last snapshot, rows today, gaps today, disk free | TODO |
| T-209 | Daily Telegram heartbeat so a death is noticed within a day | TODO |
| T-210 | `docs/RUNBOOKS/recorder.md` | TODO |

---

## Sprints 3–14 — seeded scope

| # | Build | Verify by | Status |
|---|---|---|---|
| 3 | Security master: instruments, time-versioned lot sizes, broker symbology, calendars | `make check-master` → zero unmapped symbols; lot size as of any past date | TODO |
| 4 | Bitemporal read API + lookahead firewall + adversarial test suite | `make test-lookahead` → ~15 attack tests, all blocked | TODO |
| 5 | Corporate actions + adjustment engine | `make check-adjust` reproduces a known adjusted series exactly | TODO |
| 6 | Data quality engine: gaps, OHLC sanity, MAD spikes, staleness, cross-source recon | `make quality` → counts by severity | TODO |
| 7 | Options quality: put-call parity, strike monotonicity, butterfly convexity, own IV | `make quality-options` | TODO |
| 8 | Feature library + IC harness, 10 seed features | `make ic FEATURE=momentum_12_1` → tear sheet <2 min | TODO |
| 9 | Cost model: brokerage, STT (incl. exercise), stamp duty, GST, fees, slippage, impact | `make check-costs` reproduces 20 real contract notes to the paisa | TODO |
| 10 | Tier A vectorised backtester (screening only) | `make backtest-fast STRAT=demo` | TODO |
| 11 | Tier B event-driven backtester, same `Strategy` interface as live | `make backtest` | TODO |
| 12 | **Backtester self-tests** — invariants, known-alpha recovery, zero-alpha = exact cost drag, determinism, golden files | `make test-engine` — *the most important gate in the project* | TODO |
| 13 | Overfitting battery: CPCV purge+embargo, DSR, PBO, MinBTL, tamper-evident trial counter | `make validate H=H-0001` → signed evidence pack | TODO |
| 14 | Promotion gate as code + pre-registration; locked holdout, single enforced read | Feed it 3 deliberately overfit strategies; all must be killed | TODO |

**Scope only, not yet planned:** 15–18 research agent loop · 19–24 OMS/EMS,
kill switches, first broker adapter · 25–28 paper trading + reality-gap
attribution · 29–30 compliance sprint · 31 first micro-live capital (1–2%).

---

## Discovered during Sprint 0

| ID | Item | Status |
|---|---|---|
| T-013 | Push to a private GitHub repo so CI actually runs | DONE — `Avneeshwork/eulerlab`, private |
| T-017 | Bump `actions/checkout` v4→v7 and `astral-sh/setup-uv` v5→v10 (Node 20 deprecation warning on first run) | DONE |
| T-014 | Verify the ~10 OPS SEBI threshold against the primary circular (A-001) | TODO — Sprint 29, or sooner if convenient |
| T-018 | Add Dhan as a second free feed for cross-reconciliation | DEFERRED — revisit when the quality engine (Sprint 6–7) flags anomalies a single source cannot adjudicate (ADR-004) |
| T-015 | Verify current Nifty/Sensex lot sizes and expiry days against NSE/BSE circulars (A-002, A-003) | TODO — blocking for Sprint 3 |
| T-016 | `mandate.yaml` + `gates.py` — operator-owned, written **with** the operator | TODO — Sprint 14 |
