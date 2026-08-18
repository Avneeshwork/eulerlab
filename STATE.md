# STATE — where this project is right now

**Sprint:** 1 — NSE EOD ingest
**Status:** BLOCKED
**Next:** Sprint 1 completion, once a licensed history source is chosen

**Why BLOCKED:** the downloader is built, tested and working. It is not being
run, because NSE's Terms of Use prohibit systematic automated data collection.
An operator decision on a licensed source is needed. See
`docs/SPRINT_01_REVIEW.md`.

*Last updated: 2026-08-18 (Sprint 1). One page, always current. If it is not written here or
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

## What actually works, added in Sprint 1

- **`make ingest-eod FROM=... TO=...`** downloads NSE equity and F&O bhavcopy
  into an immutable landing zone. Both archive formats handled (legacy 2015 →
  mid-2024, UDiFF 2024 →), verified against real files from both eras.
- **Re-running downloads nothing.** Proven on real data: 20.6s first run,
  1.3s second, zero re-fetches.
- **Survives a hard kill.** SIGKILL mid-run left zero partial files and every
  checksum intact; the next run resumed and fetched exactly what was missing.
- **`make check-landing`** re-hashes every landed file against the manifest,
  turning the immutability claim into a two-second check.
- **Holidays are never guessed.** A failure is FAILED, a 404 is ABSENT, and
  ABSENT is classified by cross-checking both segments — one segment missing
  while the other landed is flagged as an ANOMALY, not silently called a
  holiday.

**But it is not being run.** See the status note above.

## What does not exist yet

No usable market-data history. No database. No security master. No backtester.
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

- **The NSE backfill is blocked on terms, not on code.** A-010 resolved FALSE:
  NSE prohibits systematic automated collection. 142 files (31 MB) were
  downloaded during development before the terms were read; nothing since.
- **Most market-structure facts are still unverified.** A-001 to A-003, A-005
  to A-008, A-011, A-012 in `docs/ASSUMPTIONS.md` still rest on the reference
  playbook rather than primary sources.

## Money being spent

**₹0/month today.** Nothing is provisioned or subscribed yet. Two costs are
decided and land before Sprint 2:

| Cost | Amount | Status |
|---|---|---|
| Zerodha Kite Connect | ₹500/mo | Decided (ADR-004). Account not yet confirmed |
| Mumbai VPS | ₹500–900/mo | Decided. Not yet provisioned |

Committed run rate once both are live: **₹1,000–1,400/mo.**
