# STATE — where this project is right now

**Sprint:** 1 — NSE EOD ingest
**Status:** IN PROGRESS
**Next:** Sprint 3 — security master (Sprint 2 deferred, see TASKS.md)

**Unblocked 2026-08-18.** NSE's Terms of Use prohibit systematic automated
collection; the operator was shown this and decided to proceed regardless. The
decision and its reasoning are recorded in ADR-006 so it reads as a choice, not
an oversight. The full 2015→2026 backfill is running now, rate-limited at 1.5s
between requests, with no evasion tooling.

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
- **`make sync-cloud`** mirrors the landing zone to Backblaze B2. Planning is
  one paginated LIST (~3s for thousands of objects); `VERIFY=1` does the exact
  SHA-256 comparison as an occasional audit. Running against bucket `eulerdata`.
- **`make ingest-minute`** backfills 1-minute candles from Kite for the top-250
  universe. Chunked at 60 days (Kite's measured limit), rate limited to 3 req/s,
  Parquet per symbol per chunk, resumable from its own manifest. Symbols Kite
  cannot resolve are written to `unresolved.jsonl` rather than skipped quietly —
  those are the survivorship holes, and their size is the point.
- **Universe selection** derives the tradable set from our own bhavcopy turnover
  rather than a published index list, and refuses any lookback window with a
  hole in it. See ADR-008.
- **`make kite-login`** obtains a Kite access token. The login needs a password
  and 2FA on Zerodha's page, so it stays the operator's job; the helper does
  only the exchange that follows, locally, and writes the token to a gitignored
  `.kite_session.json` at mode 0600. Tokens expire at 06:00 IST daily, which is
  why they are not kept in `.env`.
- **Holidays are never guessed.** A failure is FAILED, a 404 is ABSENT, and
  ABSENT is classified by cross-checking both segments — one segment missing
  while the other landed is flagged as an ANOMALY, not silently called a
  holiday.

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

- **The NSE backfill runs against NSE's stated terms.** A-010 resolved FALSE
  and was then knowingly accepted by the operator (ADR-006). Not a defect, but
  the single most important thing a future reader should know about how this
  data was obtained.
- **Credentials leaked into git history and were rotated.** `ZERODHA_API_SECRET`
  and `TELEGRAM_BOT_TOKEN` are new as of 2026-08-18, verified as differing from
  the leaked values. The old ones remain in the history of
  `sprint-01-nse-eod-ingest`; a history rewrite is still an open question, but
  the live exposure is closed. See the Sprint 1 review.
- **Most market-structure facts are still unverified.** A-001 to A-003, A-005
  to A-008, A-011, A-012 in `docs/ASSUMPTIONS.md` still rest on the reference
  playbook rather than primary sources.

## Money being spent

**₹0/month today.** Nothing is provisioned or subscribed yet. Two costs are
decided and land before Sprint 2:

| Cost | Amount | Status |
|---|---|---|
| Zerodha Kite Connect | ₹500/mo | **Active** — subscription taken 2026-08-18 |
| Backblaze B2 | under ₹100/mo | **Active** — bucket `eulerdata`, mirroring |
| Mumbai VPS | ₹500–900/mo | **Deferred** — only the options recorder needs it |

**Current run rate: ~₹600/mo.** The VPS is not needed for the equities work.
