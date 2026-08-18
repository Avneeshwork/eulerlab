# STATE — where this project is right now

**Sprint:** 0 — Scaffolding
**Status:** COMPLETE
**Next:** Sprint 1 — NSE EOD ingest

*Last updated: 2026-08-18. One page, always current. If it is not written here or
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
- **CI runs and passes.** The same five gates run on every push and pull
  request at `github.com/Avneeshwork/eulerlab` (private). First run: green in
  13 seconds.

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

## Decisions taken (2026-08-18)

| Decision | Choice | Recorded in |
|---|---|---|
| Repository | Private GitHub repo `Avneeshwork/eulerlab`, CI verified green | this file |
| Sprint 2 live data source | Zerodha Kite Connect only, ₹500/mo | ADR-004 |
| Sprint 1 EOD history range | From 2015-01-01 | `TASKS.md` T-102 |
| Sprint 2 hosting | Mumbai VPS before Sprint 2, not the laptop | `TASKS.md` T-202 |

## Known issues

- **Nothing is verified against a primary source yet.** Every market-structure
  fact in the docs came from `docs/quant_platform_playbook.md` and carries a
  recheck date in `docs/ASSUMPTIONS.md`. Sprint 1 starts fixing that.

## Money being spent

**₹0/month today.** Nothing is provisioned or subscribed yet. Two costs are
decided and land before Sprint 2:

| Cost | Amount | Status |
|---|---|---|
| Zerodha Kite Connect | ₹500/mo | Decided (ADR-004). Account not yet confirmed |
| Mumbai VPS | ₹500–900/mo | Decided. Not yet provisioned |

Committed run rate once both are live: **₹1,000–1,400/mo.**
