# AI Build Plan — how I build the quant platform and how you verify it

*Companion to `quant_platform_playbook.md` (the what). This document is the how.*

---

## 0. The core idea in one paragraph

I cannot work for weeks without stopping. Each session with me has a memory limit. So the whole system is designed around one rule: **all state lives in the repo, never in my head.** Every session I start by reading three files (`CLAUDE.md`, `STATE.md`, `TASKS.md`), do one sprint of work, then update those files and write a review page for you. If I disappear mid-way, the next session picks up exactly where the files say we are. You never have to remember anything either — you just read the review page and run one command.

This is the difference between "AI helped me code" and "AI ran a project."

---

## 1. What you actually do (your job is small)

Per sprint you do three things, in about 10–15 minutes:

| Type | What it means | How long |
|---|---|---|
| **GLANCE** | Read `docs/SPRINT_NN_REVIEW.md`. One page. Plain English. | 3 min |
| **RUN** | Type `make verify` in the terminal. It prints a green/red table. | 2 min |
| **DECIDE** | Answer numbered questions I put at the bottom of the review. Only these block progress. | 5–10 min |

You never read code unless you want to. You never need to remember what sprint we're on. If `make verify` is green and the review has no open questions, say "next sprint" and I continue.

**My honesty obligations to you**, enforced by the review template:
- Every review has a **"What is fake right now"** section listing stubs, mocks and hardcoded values. Nothing gets quietly faked.
- Every review has a **"What I could not verify"** section. If I guessed, I say I guessed.
- If a sprint failed, the review says FAILED at the top. No burying it in paragraph four.

---

## 2. How I do research on my own

Research is not "I read some stuff and formed an opinion." It's a task type with a fixed output file, so you can audit it.

### 2.1 The research loop

```
question → search web → fetch primary sources → extract structured facts
    → write docs/RESEARCH/NNN-topic.md → make a decision → log it as an ADR
    → anything unproven goes into docs/ASSUMPTIONS.md with a recheck date
```

**Hard rule I follow:** any fact that drives a design decision needs a source URL and the date I fetched it. If I can't source it, it goes in `ASSUMPTIONS.md` marked UNVERIFIED, and the code gets a `# ASSUMPTION:` comment. You can then grep for every place the system rests on a guess. This is the single most useful discipline for keeping AI-built systems trustworthy.

### 2.2 What I can and cannot reach

**Can reach, free:** arXiv, SSRN, NBER, ResearchGate preprints, RePEc, Google Scholar landing pages, SEBI circulars, NSE/BSE circulars and archives, exchange contract specs, broker API docs, GitHub, quant blogs (Quantocracy, Robot Wealth, Hudson & Thames), CFTC/SEC filings, Federal Reserve/RBI publications.

**Cannot reach:** paywalled journals (Journal of Finance, RFS, JFE final versions), Bloomberg/Refinitiv terminals, paid vendor docs behind login. For paywalled papers I find the working-paper version — for finance, the SSRN/NBER preprint exists ~90% of the time and is usually close enough.

So the accessible research corpus is genuinely large. This is not a real constraint.

### 2.3 How I read a paper (output is a spec, not a summary)

Prose summaries are useless for building. Every paper becomes a machine-readable hypothesis card:

```yaml
# hypotheses/H-0042.yaml
paper: "Residual Momentum in Emerging Markets"
url: https://papers.ssrn.com/...
fetched: 2026-08-20
claim:
  universe: "emerging market large+mid caps"
  signal: "12-month return residualised on local market + size + value, skip 1 month"
  horizon_days: 21
  rebalance: monthly
  reported_sharpe: 0.94
  sample: 1996-2018
  costs_assumed: "10bps one-way"       # ← almost always too optimistic
mechanism: >
  Thin analyst coverage slows information diffusion; local institutions
  rebalance slowly. Compensation is for holding stale-information risk.
transplant_to: [india_nifty500]
red_flags: ["sample predates 2019", "costs unrealistic for India", "no F&O ban handling"]
status: untested
```

Then I test it against **your** data with **your** costs. Most will die. That's the process working, not failing.

### 2.4 Data and event analysis

Two scheduled jobs, both cheap, both running from week one:

**Event monitor** (daily, ~5 min of compute): pulls NSE + BSE + SEBI circular RSS/listing pages, diffs against yesterday, files anything about contract specs, lot sizes, expiry changes, margin rules, or new products into `docs/EVENTS/YYYY-MM.md` and flags it in the next review. This is how you never again get surprised by a lot-size revision breaking your backtests. It is also a *strategy idea source* — market-structure changes create mechanically explainable inefficiencies.

**Data profiler** (weekly): re-runs the quality battery over the whole history and reports drift — new gaps, vendor backfills, distribution shifts. Catches the silent data corruption that would otherwise become fake alpha.

Analysis output always goes to `reports/NNN-question.md` with the script that made it committed next to it. If a chart isn't reproducible by running one script, it doesn't count.

---

## 3. The cheap stack (what I'll actually use)

Simple principle: **for the first 6 months, buy nothing you can avoid.** Everything below runs on a laptop plus one tiny server.

### Months 1–6 — near-zero cost

| Need | Cheap choice | Cost |
|---|---|---|
| Storage | Parquet files on local disk + external HDD backup | ₹0 |
| Time-series DB | **DuckDB** (a file, not a server) | ₹0 |
| Versioned store | ArcticDB on local filesystem (upgrade to S3 later, same API) | ₹0 |
| India EOD data | NSE/BSE archives: bhavcopy, F&O bhavcopy, participant-wise OI, bulk/block deals | ₹0 |
| India intraday + live | Zerodha Kite Connect (or Dhan, whose API is free) | ₹0–500/mo |
| **Options chain history** | **Record it yourself starting day one** (see below) | ₹500/mo VPS |
| US data | yfinance for prototyping, Alpaca free tier, Polygon free tier | ₹0 |
| Crypto | Binance public historical dumps + free WebSocket | ₹0 |
| FX | Dukascopy free tick archive | ₹0 |
| Orchestration | plain `cron` + Python. No Airflow, no Dagster yet. | ₹0 |
| Dashboards | Streamlit run locally, or markdown reports | ₹0 |
| Server | 1 small VPS in Mumbai (Hetzner/DigitalOcean/AWS Lightsail) | ₹500–900/mo |
| Version control | GitHub free private repo + GitHub Actions free tier for CI | ₹0 |
| **Total** | | **₹1,000–1,500/mo** |

**The single most valuable thing you can do this week:** start the options-chain snapshot recorder. Nobody sells cheap Indian option-chain history with clean timestamps. Every day you don't record is a day of data you can never get back at any price. A ₹500/mo VPS writing a snapshot every 5 seconds from today builds, in one year, an asset that would cost lakhs to buy — if you could buy it at all. **This is Sprint 2. Before the fancy stuff.**

### Months 6–12 — add only what a measurement proves you need

| Trigger | Then add | Cost |
|---|---|---|
| Need pre-2026 options history you didn't record | TrueData or GDFL historical | ₹1,000–3,000/mo |
| Local disk full / need remote access | Backblaze B2 or S3 (~₹150/TB/mo) | ₹200–800/mo |
| Cron jobs becoming a tangle | Dagster (open source, self-hosted) | ₹0 |
| Backtests taking hours | One bigger VPS, or 8 hours of a spot instance | ₹500–2,000/mo |
| Going live | Second broker account, static IP | ₹0–500/mo |

**Deliberately skipped for a long time:** Kubernetes, Kafka, ClickHouse, kdb+, cloud data warehouses, paid observability, GPUs. Each of these is correct at scale and pure overhead below it. The playbook's full stack is the destination, not the starting point.

**One real cost to plan for:** my own usage. Heavy Claude Code sessions on a project this size are a genuine monthly line item. Keep sessions focused (one sprint each) and it stays reasonable.

---

## 4. Documentation, written as we go

Not a phase at the end. Every sprint writes docs or `make verify` fails.

```
repo/
├── CLAUDE.md               ← my operating rules. I read this every session.
├── STATE.md                ← one page: where we are right now
├── TASKS.md                ← the ledger. Every task, status, verify command.
├── Makefile                ← make verify, make test, make docs, make report
├── docs/
│   ├── DECISIONS/          ← ADR-001-why-duckdb.md  (context/options/choice/cost)
│   ├── RESEARCH/           ← 001-nse-bhavcopy-schema.md (question/sources/findings)
│   ├── READING/            ← index.md — your reading list, auto-maintained
│   ├── EVENTS/             ← 2026-08.md — circulars and market-structure changes
│   ├── RUNBOOKS/           ← what to do when X breaks
│   ├── ASSUMPTIONS.md      ← every unverified claim + recheck date
│   ├── STUBS.md            ← everything currently fake
│   ├── GLOSSARY.md         ← plain-English definitions
│   ├── COMPLIANCE_DEFERRED.md  ← the deferred list + when each becomes blocking
│   └── SPRINT_NN_REVIEW.md ← your one-pager per sprint
├── src/                    ← the code
├── tests/
├── hypotheses/             ← H-NNNN.yaml strategy specs from papers
├── reports/                ← analysis outputs + the script that made them
└── data/                   ← gitignored. landing/ curated/ features/
```

**Four document types and what each is for:**

- **ADR (Architecture Decision Record)** — five lines. *We chose X because Y; we rejected Z because W; the cost of being wrong is V.* Written when a choice is made, never later. This is what stops "why on earth is it built this way" six months from now.
- **Research note** — question, sources with URLs and dates, findings, decision, confidence, open questions.
- **Runbook** — written the first time something breaks, before the fix is forgotten.
- **Sprint review** — your one-pager.

**Enforced in CI:** a commit touching `src/` with no corresponding doc change fails the docs check. Sounds bureaucratic; in practice it takes 90 seconds per sprint and it is the reason the project stays understandable.

---

## 5. Your reading list, built automatically

You asked to be told what to read. Every task carries a `READ:` block, and I roll them up into `docs/READING/index.md`, sorted by when you'll need it:

```markdown
## MUST READ before Sprint 4 (approving the backtester design)
- **Survivorship & lookahead bias** — 20 min
  Why: Sprint 4 builds the firewall that prevents these. You need to be able
  to tell if my test suite actually tests the right thing.
  Source: López de Prado, AFML ch.1–3, OR the free "Backtesting" chapter notes
  Test yourself: can you explain why using today's Nifty 50 list on 2015 data
  inflates returns?

## SHOULD READ this month
- **How SPAN margin works** — 45 min. Needed for Sprint 13.
- **Bitemporal data modelling** — 30 min. Explains why every table has two dates.

## LATER (before we touch options)
- **Black-76 vs Black-Scholes** — why Indian index options use the futures variant
- **SVI volatility surface parameterisation**
```

Three tiers only: **MUST** (blocks your ability to verify the next sprint), **SHOULD** (this month), **LATER**. Each entry says *why it matters for the specific decision you're about to make* — not a generic textbook list. Total MUST reading across the whole project is roughly 15–20 hours, spread over a year.

---

## 6. Sprint plan

One sprint ≈ one session with me ≈ one runnable thing. Sprints 0–14 are specified; beyond that the playbook's phases apply and we plan 3 sprints ahead.

| # | Build | You verify by | READ topics |
|---|---|---|---|
| **0** | Repo skeleton, `CLAUDE.md`, `STATE.md`, `TASKS.md`, Makefile, CI, doc templates. Nothing trades. | `make verify` shows the harness working on a dummy check | Git basics if needed; nothing else |
| **1** | NSE EOD downloader → landing zone. Idempotent (re-run is safe), resumable, rate-limited, caches raw files forever. | `make ingest-eod` twice; second run downloads nothing. Row counts printed. | Idempotency; why raw data is immutable |
| **2** | **Options chain recorder live on the VPS.** Snapshots Nifty + Sensex chains every 5s during market hours. Starts collecting today. | Check the VPS wrote files today; `make recorder-status` | Nothing — just get it running |
| **3** | Security master: instruments, time-versioned lot sizes, broker symbology mapping, trading calendars (India first). | `make check-master` → zero unmapped symbols; query Nifty lot size as of any past date and get the right answer | Point-in-time data; why symbols are never join keys |
| **4** | **Bitemporal read API + lookahead firewall.** Plus an adversarial test suite that actively tries to leak the future. | `make test-lookahead` → shows ~15 attack tests, all blocked | **MUST: lookahead & survivorship bias** |
| **5** | Corporate actions + adjustment engine. Splits, bonuses, dividends, symbol changes, F&O contract adjustments. | `make check-adjust` reproduces a known adjusted series exactly | Ratio vs difference adjustment |
| **6** | Data quality engine: gaps, OHLC sanity, MAD spike detection, staleness, cross-source reconciliation. | `make quality` → report with counts by severity | Robust statistics (why MAD not stdev) |
| **7** | Options quality: put-call parity, strike monotonicity, butterfly convexity, calendar arb, own IV calculation. | `make quality-options` on your recorded chains | **MUST: no-arbitrage bounds**; Black-76 |
| **8** | Feature library + IC harness. 10 seed features, tear sheet in under 2 min. | `make ic FEATURE=momentum_12_1` → tear sheet | **MUST: Information Coefficient**, factor neutralisation |
| **9** | Cost model. India first: brokerage, STT (incl. exercise), stamp duty, GST, exchange fees, slippage, impact. | `make check-costs` reproduces 20 of your real contract notes to the paisa | Indian transaction taxes; square-root impact law |
| **10** | Tier A vectorised backtester. Fast, approximate, conservative. For screening only. | `make backtest-fast STRAT=demo` | Vectorised vs event-driven |
| **11** | Tier B event-driven backtester, same `Strategy` interface as live will use. | `make backtest` + the three self-tests below | **MUST: event-driven architecture** |
| **12** | Backtester self-tests: accounting invariants per event, known-alpha recovery, zero-alpha = exact cost drag, determinism, golden files. | `make test-engine` → all green. **This is the most important gate in the project.** | Property-based testing |
| **13** | Overfitting battery: CPCV with purge+embargo, DSR, PBO, MinBTL, stress tests, tamper-evident trial counter. | `make validate H=H-0001` → signed evidence pack PDF | **MUST: CPCV, Deflated Sharpe, PBO** |
| **14** | Promotion gate as code + pre-registration workflow. Locked holdout with enforced single read. | Deliberately feed it 3 overfit strategies; all must be killed | Multiple testing, t>3 rule |
| 15–18 | Research agent loop: paper scout → hypothesis cards → codegen → critic → orchestrator. First 20 hypotheses through the gate. | Weekly: hypotheses tested, passed, killed, and why | Agent guardrails; trial counting |
| 19–24 | OMS/EMS, order state machine, idempotent client IDs, reconciler, kill switches, first broker adapter (paper). | Chaos tests: kill process mid-order, pull network | **MUST: idempotency, order state machines** |
| 25–28 | Paper trading + reality-gap attribution dashboard. | Daily attribution report; residual under 10% | Implementation shortfall |
| 29–30 | **Compliance sprint** (deferred here per your instruction): static IP, Algo-ID wiring, OPS governor tuning, broker framework confirmation, CA review of tax treatment. | Written memo + broker confirmation in hand | SEBI algo framework |
| 31 | **First micro-live capital, 1–2%.** | Watch it for a month | — |
| 32+ | India options stack → portfolio allocator → US market → crypto. Playbook Phase 7 onward. | Per playbook gates | — |

**Realistic pace:** 1–3 sprints a week if you're responsive on decisions. Sprints 0–14 in roughly 2–3 months. First live capital around month 7–9. That is much faster than the playbook's 18-month timeline because we're skipping the enterprise stack and deferring compliance — the trade-off is a smaller, simpler system, which for one person's capital is the right call.

---

## 7. Compliance: deferred, with three stubs kept

Per your instruction, the compliance memo moves to Sprint 29–30, right before live. I'm keeping exactly three things now, because they're cheap today and expensive to retrofit:

1. **`algo_id` field in the order schema** — nullable, unused, present. Adding a field to a schema now: 5 minutes. Adding it after the OMS, reconciler, event log and attribution system all exist: a week of migrations.
2. **An OPS governor with a config key** — `max_orders_per_second: 5`, enforced in the EMS from day one. It's a good engineering safeguard regardless of regulation, and it means the compliance sprint is a config change, not a redesign.
3. **`static_ip` in the deploy config** — a placeholder value. Costs nothing.

`docs/COMPLIANCE_DEFERRED.md` tracks the full deferred list with the trigger that makes each one blocking, so nothing gets lost:

| Deferred item | Becomes blocking at |
|---|---|
| Broker framework confirmation + static IP registration | Sprint 29 (before any live order) |
| Algo-ID passthrough tested end-to-end | Sprint 29 |
| CA review: F&O business income, STCG/LTCG, VDA treatment | Sprint 29 |
| LRS/FEMA position for US trading | Before the US market sprint |
| Crypto TDS cost modelling | Before any crypto strategy is backtested (it's a cost input, not paperwork) |

---

## 8. How I start next prompt

### 8.1 Your setup, once (15 minutes)

1. Install Claude Code (terminal or your IDE's extension).
2. Make an empty folder: `mkdir quantlab && cd quantlab && git init`
3. Install Python 3.12+ and `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
4. Optional now, needed by Sprint 2: a small Mumbai-region VPS.
5. Open Claude Code in that folder and paste the kickoff prompt from `sprint_01_kickoff.md`.

### 8.2 What I do in Sprint 0

I'll create, in one session:
- `CLAUDE.md` — my permanent operating rules (full draft is in the companion file, ready to use)
- `STATE.md`, `TASKS.md` seeded with sprints 0–14
- `Makefile` with `verify`, `test`, `docs`, `report`, `state`
- `pyproject.toml`, `uv` lockfile, `ruff` + `mypy --strict` config, pre-commit hooks
- `docs/` tree with every template filled in as an example, not left blank
- `.github/workflows/ci.yml` — tests + lint + typecheck + the docs check
- `docs/READING/index.md` seeded with your MUST-read list for sprints 1–4
- `docs/SPRINT_00_REVIEW.md` — your first one-pager
- A deliberately trivial dummy module and test, so `make verify` proves the harness works end to end

**Your verification for Sprint 0:** run `make verify`. It should print a table, all green. Read the review page. Answer any decision questions. Say "next".

### 8.3 The session protocol I follow every time

**On start:** read `CLAUDE.md` → `STATE.md` → `TASKS.md` → state the sprint goal and my plan in 5 bullets → **wait for your go**. I don't start writing code until you've seen the plan. That's your steering wheel, and it costs you 30 seconds.

**During:** small commits with conventional messages. Tests written with the code, not after. Any factual claim gets a source or an `# ASSUMPTION:` tag. Anything faked gets logged to `STUBS.md` the moment I fake it.

**On end:** update `STATE.md` and `TASKS.md` → write `docs/SPRINT_NN_REVIEW.md` → append to `docs/READING/index.md` → commit → tell you the one command to run.

**If I run out of room mid-sprint:** I stop, write an honest partial review saying exactly what's done and what isn't, update the ledger, and commit. The next session resumes cleanly. No half-finished work lost, no lying about progress.

---

## 9. The three rules that keep this honest

Everything else is detail. These three are load-bearing.

1. **The repo is the memory.** If it isn't in `STATE.md` or `TASKS.md`, it didn't happen. This makes an AI-run project resumable and auditable, and it means you can hand this to a human engineer later without a knowledge transfer.

2. **I build the brake before the accelerator.** The lookahead firewall (Sprint 4) and the engine self-tests (Sprint 12) come before any real strategy work. The kill switches come before the first live order. An AI that can generate 100 strategies a month against a leaky validation process is a machine for losing money efficiently.

3. **The gate is code, and I never touch it.** `gates.py` and `mandate.yaml` are yours. I write them once, in Sprint 14, with you. After that, if a strategy of mine fails the gate, the strategy dies — I don't get to argue, adjust the threshold, or run "just one more variant." Any change to those two files requires your explicit commit. This is the one place where my autonomy is deliberately zero, and it's the reason the rest of the autonomy is safe.
