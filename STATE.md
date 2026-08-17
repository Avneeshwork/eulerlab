# STATE — where this project is right now

**Sprint:** 0 — Scaffolding
**Status:** PARTIAL
**Next:** Sprint 1 — NSE EOD ingest

**Why PARTIAL:** five of six acceptance criteria pass. The sixth — "CI passes on
a pushed branch" — cannot be checked because there is no GitHub remote. See
`docs/SPRINT_00_REVIEW.md` question 1.

*Last updated: 2026-08-17. One page, always current. If it is not written here or
in `TASKS.md`, it did not happen.*

---

## What actually works today

- **`make verify`** runs five gates — lint, types, tests, docs-check, state — and
  prints one table. This is the only command needed to check the repo is sound.
- **The docs gate has teeth.** A commit that changes `src/` without changing any
  documentation fails. Proven by tests in `tests/test_docs_check.py`, which build
  throwaway git repositories and confirm both the pass and the fail case.
- **Typed config loading.** `config/*.yaml` is parsed into frozen Pydantic models
  with `extra="forbid"`, so a misspelled key is a startup error, not a silently
  ignored setting.
- **CI** runs the same five gates on every push and pull request.

## What does not exist yet

No market data. No downloader. No database. No security master. No backtester.
No strategy. Nothing connects to a broker, and nothing trades. Sprint 0 built the
harness that makes every later sprint checkable in two minutes — that is all.

## What is faked or reserved

Three compliance placeholders exist as config and schema only, per the build
plan. All three are logged in `docs/STUBS.md`:

| Placeholder | Where | Real in |
|---|---|---|
| `algo_id` field on an `Order` model | `src/eulerlab/schemas.py` | Sprint 19 |
| `max_orders_per_second: 5` | `config/execution.yaml` | Sprint 19 |
| `static_ip: null` | `config/deploy.yaml` | Sprint 29 |

## Known issues

- **No GitHub remote.** `.github/workflows/ci.yml` is written but has never run.
  It is unverified until the repo is pushed. See `docs/SPRINT_00_REVIEW.md` Q1.
- **Nothing is verified against a primary source yet.** Every market-structure
  fact in the docs came from `docs/quant_platform_playbook.md` and carries a
  recheck date in `docs/ASSUMPTIONS.md`. Sprint 1 starts fixing that.

## Money being spent

₹0/month. No VPS, no data subscription, no cloud account. The first recurring
cost is the Sprint 2 VPS (~₹500–900/mo) and it is not yet provisioned.
