# CLAUDE.md — operating rules for this repository

**Read this file, then `README.md`, then `STATE.md`, then `TASKS.md`, at the start of every session. Before writing any code, state the goal and your plan in 5 bullets and wait for the operator's approval.**

The build plan's sprints are finished. Work is now task-driven from `TASKS.md`, not sprint-driven, so there are no new `SPRINT_NN_REVIEW.md` files — the eighteen that existed are consolidated into `docs/HISTORY.md`.

---

## Project

A quant research and execution platform. Markets in rollout order: India equities → India index options → US equities → US options → crypto → FX. Reference design: `docs/quant_platform_playbook.md`. Build process: `docs/AI_BUILD_PLAN.md`.

Single operator, single-person capital. Optimise for correctness and low cost, not scale.

---

## The operator's role

They verify, they don't code. Everything you produce must be checkable by:
1. Reading one page (`docs/SPRINT_NN_REVIEW.md`)
2. Running one command (`make verify`)
3. Answering numbered decision questions

If a piece of work can't be verified that way, it isn't finished.

---

## Session protocol

**Start**
1. Read `CLAUDE.md`, `STATE.md`, `TASKS.md`.
2. Identify the task and how it will be verified.
3. State the goal and a 5-bullet plan. **Stop and wait for approval.**

**During**
- One sprint per session. Do not start the next sprint early.
- Tests are written alongside code, never "later".
- Commit in small increments, conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- Work on a branch named `sprint-NN-short-name`.

**End**
1. Update `STATE.md` — and keep it **one page**. It is a summary, not a log.
2. Update `TASKS.md` (statuses, new tasks discovered).
3. If the work changed how the system behaves, update `docs/ARCHITECTURE.md`.
4. If it proved something earlier wrong, add it to `docs/HISTORY.md`. That file
   is the project's memory of its own errors and is more valuable than the
   record of its successes.
5. Commit. Tell the operator the single command to run.

**If out of context mid-sprint:** stop cleanly. Write an honest partial review stating exactly what is done and what is not. Update the ledger. Commit. Never overstate progress.

---

## Hard rules

### Truth
- Every factual claim that drives a design decision needs a source URL and fetch date in `docs/RESEARCH/`, **or** an entry in `docs/ASSUMPTIONS.md` plus an `# ASSUMPTION:` comment at the point of use.
- Anything stubbed, mocked or hardcoded goes into `docs/STUBS.md` **at the moment it is created**, not at review time.
- Never report a sprint as complete if its acceptance criteria fail. Write FAILED at the top of the review.
- Never invent a data source, API endpoint, library function, or regulatory detail. If unsure, search; if still unsure, say so.

### Data integrity
- Raw downloaded data is immutable. It lands in `data/landing/`, is never edited, never deleted.
- All ETL is idempotent and resumable. Re-running must be safe and must not re-download.
- Every stored record carries `event_time` and `knowledge_time`. No exceptions.
- The research read API takes an `as_of` and must be structurally incapable of returning `knowledge_time > as_of`. This is enforced at the data layer, not by caller discipline.
- Instrument joins use internal IDs only. Never a ticker, tradingsymbol, or broker token.
- Lot size, tick size and multiplier are time-versioned fields. **Never hardcode them.**

### Code
- Python 3.12+, `uv` for dependencies. `mypy --strict` on `src/`. `ruff` clean.
- Pydantic for every config and data contract.
- No secrets in the repo, ever. `.env` is gitignored; `.env.example` is committed.
- Determinism: seed everything. Same input must give byte-identical output.
- One `Strategy` interface, used unchanged by Tier A backtest, Tier B backtest, paper and live. If those diverge, stop and fix the abstraction.

### Validation
- `gates.py` and `mandate.yaml` are operator-owned. You may propose changes in a review; you may not edit them without an explicit instruction in that session.
- Every strategy configuration evaluated increments the trial counter in the append-only log. Never bypass it, never reset it.
- A strategy that fails the gate is dead. Do not tune it and resubmit. Do not argue with the gate.
- The holdout dataset is read exactly once, by the operator's action. Never read it to "check something".

### Money safety (from the OMS sprint onward)
- Client order IDs are deterministic: `hash(strategy_id, signal_time, instrument_id, seq)`. Retries must never double-send.
- The broker is the source of truth. Local position state is a cache.
- An `UNKNOWN` order state is resolved by querying, never by assuming.
- Order schema includes `algo_id` (nullable) from day one.
- EMS enforces `max_orders_per_second` from config, default 5.
- Kill switches are implemented in a separate process with separate credentials from the strategies.

---

## Documentation, written with the code

A commit touching `src/` with no corresponding documentation change fails CI.

| Type | Path | When | Length |
|---|---|---|---|
| Decision record | `docs/DECISIONS/ADR-NNN-slug.md` | At the moment a choice is made | 5 lines: context, options, choice, why, cost if wrong |
| Research note | `docs/RESEARCH/NNN-slug.md` | Whenever you search the web to answer a design question | Question, sources (URL + date), findings, decision, confidence, open questions |
| Runbook | `docs/RUNBOOKS/slug.md` | First time something breaks | Symptom, diagnosis, fix, prevention |
| Correction | `docs/HISTORY.md` | Whenever something earlier is proved wrong | What was believed, what is true, which numbers are now invalid |
| Event log | `docs/EVENTS/YYYY-MM.md` | Any exchange/regulatory change found by the monitor | Date, source, what changed, what it breaks |

---

## The five documents

They do not overlap. Put a fact in exactly one of them.

| Question | Document |
|---|---|
| How does it work, and what is the maths? | `docs/ARCHITECTURE.md` |
| Where is the project right now? | `STATE.md` — **one page** |
| What is still open? | `TASKS.md` |
| What was built, and what did it get wrong? | `docs/HISTORY.md` |
| What are the rules for working here? | `CLAUDE.md` |

Supporting records keep their existing roles: `docs/STUBS.md` (what is fake),
`docs/ASSUMPTIONS.md` (what is unverified, with recheck dates),
`docs/DECISIONS/` (why), `docs/RESEARCH/` (what sources said),
`docs/RUNBOOKS/` (what to do when it breaks).

**Generated files are not documentation.** `web/public/architecture.html` is
built from `docs/ARCHITECTURE.md` by `tools/render_architecture.py` and is
gitignored. Never edit it; never commit it.

## Research protocol

When answering a design question that depends on external facts:

1. Search. Prefer primary sources: SEBI/NSE/BSE circulars, exchange contract specs, broker API docs, arXiv/SSRN/NBER preprints, official library docs.
2. Fetch the actual page. Do not rely on search snippets for anything that matters.
3. Record in `docs/RESEARCH/NNN-slug.md` with URLs and fetch dates.
4. Note explicitly what you could **not** find. Absence of evidence is a finding.
5. If a paywalled paper is needed, find the working-paper version and say which version you read.
6. Turn any strategy paper into a `hypotheses/H-NNNN.yaml` spec, not a prose summary. Include a `red_flags` list.
7. Regulatory and contract-spec facts get a recheck date in `docs/ASSUMPTIONS.md` — these change often.

---

## Cost discipline

Default to free and local. Before proposing any paid service or heavyweight dependency, write one line in the review: what it costs, what it replaces, and what measurement showed we need it. No Kubernetes, Kafka, ClickHouse, cloud warehouses, or paid observability until a measured constraint justifies it.

---

## Style

Plain English in all documentation — the operator is verifying, not admiring. Short sentences. Say what broke. Never pad a review to look productive. If a sprint delivered less than planned, say so in the first line.
