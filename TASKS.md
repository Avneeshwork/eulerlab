# TASKS — the ledger

Every task, its status, and the command that proves it. Statuses:
**TODO** · **DOING** · **DONE** · **BLOCKED** · **KILLED**

Sprints 0–14 are seeded from `docs/AI_BUILD_PLAN.md` §6 and
`docs/sprint_01_kickoff.md`. Sprints 15+ are planned three ahead, per the build
plan — they are listed here as scope only, not as tasks.

---

## Sprint 4 — lookahead firewall (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-401 | Bitemporal read API, `as_of` required and keyword-only | DONE — ADR-014 |
| T-402 | Adversarial test suite against the firewall | DONE — 36 tests, `make test-lookahead` |
| T-403 | Wire the store to real landing-zone manifests | DONE — found the download-time defect |
| T-404 | Separate knowledge time from receipt time | DONE — ADR-015, `make provenance` |
| T-405 | Point-in-time universe guard (survivorship) | DONE — `bitemporal/universe.py` |
| T-406 | Source the real NSE publication hour per segment | OPEN — A-014, before Sprint 9 or any intraday work |
| T-407 | Persist the store to Parquet when a dataset exceeds memory | OPEN — no measured need yet |

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

## Sprint 1 — NSE EOD ingest · **IN PROGRESS** (backfill running)

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
| T-113 | Decide a history source given NSE's terms | DONE — operator chose to proceed from the public archive anyway (ADR-006) |
| T-115 | Run the full 2015→2026 backfill | IN PROGRESS — ~5,800 requests, ~6–7 hours, resumable |
| T-116 | `make sync-cloud` — mirror the landing zone to Backblaze B2 (ADR-007) | DONE (code) — **unwired**, needs bucket + key |
| T-117 | Create the B2 bucket and an application key, fill `config/storage.yaml` and `.env` | TODO — operator action, blocks T-118 |
| T-118 | Run the first full cloud sync and verify every checksum | BLOCKED — needs T-117 |
| T-102 | Bhavcopy + F&O bhavcopy downloader into `data/landing/`, gzipped, one file per day | DONE |
| T-103 | Idempotency: re-run downloads zero files and says so | DONE — proven on real data, 20.6s then 1.3s |
| T-104 | Resumability: Ctrl-C mid-run, restart, resumes correctly | DONE — proven against SIGKILL, stronger than Ctrl-C |
| T-105 | Rate limiting + retry with backoff | DONE |
| T-106 | Summary output: date range, fetched, skipped, rows parsed, holidays | DONE |
| T-107 | Missing-day report distinguishing "market holiday" from "download failed" | DONE — three honest states, never guesses |
| T-108 | Landing zone is immutable — files never modified after write, enforced by test | DONE — `make check-landing` |

---

## Sprint 2 — Options chain recorder · **DEFERRED** (2026-08-18, operator decision)

**Deferred in favour of finishing the equities stack first.** The reasoning
against deferring is on the record and unchanged: NSE sells no cheap historical
option-chain data, so every day the recorder is not running is a day that cannot
be bought back at any price. Measured cost of doing it: full chains at 5s is
~300-550 MB/day; **near-expiry-only is ~35-65 MB/day**, roughly a tenth, and
still captures the irreplaceable part. Worth revisiting as a background job.

The blocking research is already done and does not expire — see
`docs/RESEARCH/003-kite-feasibility-for-the-options-recorder.md`: the recorder
must be WebSocket-based, because polling the full chains takes 9 seconds against
a 5-second target.

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

## The equities path — next up

With options deferred, sprints 3-6 need **nothing from the operator**: no VPS,
no new spending, all local computation over data already landed.

| # | Build | Verify by | Status |
|---|---|---|---|
| 3 | Security master: instruments, time-versioned lot sizes, calendars | `make check-master` | **NEXT** |
| 4 | Bitemporal read API + lookahead firewall | `make test-lookahead` | TODO |
| 5 | Corporate actions + adjustment engine | `make check-adjust` | TODO |
| 6 | Data quality engine | `make quality` | TODO |

Sprint 7 (options quality) moves to wherever the recorder lands.

## Sprint 3 — security master · **COMPLETE**

Verify: `make verify` and `make check-master` (6 of 6)

| ID | Task | Status |
|---|---|---|
| T-301 | Internal instrument id, measured not assumed (ADR-012) | DONE |
| T-302 | Time-versioned registry, `at(as_of)` returns what was true then | DONE |
| T-303 | Build from bhavcopy, streaming from B2 | DONE |
| T-304 | Symbol-change map from ISIN continuity — 580 renames | DONE |
| T-305 | Succession model: rename / merger / demerger / cancellation (ADR-013) | DONE |
| T-306 | Fix the BE-series lookup bug (4 false delistings) | DONE |
| T-307 | Refetch minute bars for 24 recovered symbols | DONE — 420 symbols, 184M bars |
| T-308 | F&O composite key (symbol, expiry, strike, right) | DONE — 28,984 contracts in 2015 and 35,089 in 2026 parsed, zero failures, zero duplicate keys |
| T-309 | Trading calendar from evidence, not weekday rules | DONE — 2,869 trading days; flags 2021-03-30 SUSPECT rather than guessing |
| T-310 | `make check-master` | DONE — 6 checks, all green, each capable of failing |
| T-311 | Verify lot-size history against a known past value (A-002) | DONE — NIFTY 50/25/75/65 read from our own bhavcopy; A-002 resolved |
| T-312 | Resolve TATACOFFEE ratio | DONE — one scheme, two legs: 1/22 + 14/55 = 3/10 exactly. Sources never disagreed |
| T-313 | Research DHANI, JPASSOCIAT successions | DONE — DHANI→IBULLSLTD (terms_pending), JPASSOCIAT delisted in insolvency |

## Sprints 4–14 — seeded scope

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

| T-314 | Persist the master with a build stamp | DONE — JSONL, deterministic, `make build-master` |
| T-315 | Broker symbology map (internal id ↔ Kite token) | DONE — 71.9% of mappable equities; residual is SME listings absent from the main board |
| T-316 | Ingest SME-platform listings so the broker map reaches 100% | **SKIPPED** — operator decision 2026-08-19. SME names are illiquid and outside the tradable universe; 71.9% coverage of main-board equities is the intended scope, not a shortfall |
| T-317 | Run `make build-master --cadence daily` once, to catch renames that reverse inside a month | TODO |
