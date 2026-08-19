# STATE — where this project is right now

**Sprint:** 3 — security master
**Status:** PARTIAL
**Next:** finish Sprint 3 (F&O keys, calendar, `make check-master`), then Sprint 4

*Last updated: 2026-08-19 07:40 IST. One page, always current. If it is not
written here or in `TASKS.md`, it did not happen.*

---

## Datasets — what exists

| Dataset | State | Coverage |
|---|---|---|
| NSE EOD bhavcopy (cash + F&O) | **COMPLETE** | 5,737 files, 2015-01-01 → 2026-08-17. One known source gap: no F&O for 2021-03-30 (S-009) |
| Participant-wise F&O OI | **COMPLETE** | 1,639 days, 2020 → today, **zero gaps** |
| Kite 1-minute bars | **COMPLETE** | 13,499 chunks, 420 symbols, **184M bars**, 5 years |
| screener.in fundamentals | **COMPLETE** | 2,352 companies (328 no data, 22 404s — mostly ETFs) |
| Options chains / tick data | **NOT STARTED** | deferred by the operator three times |

Everything is mirrored to Backblaze B2 bucket `eulerdata`. Local disk holds a
working subset only; files are pruned after B2 confirms them (ADR-010) and
restored with `make restore-local`.

## Sprint 3 — what is built

- **`eulerlab.master.identity`** — the internal id. Company equity (`INE`) keys
  on the ISIN *issuer prefix*; fund units (`INF`) key on the full ISIN. Both
  rules are measured, not assumed (research note 006, ADR-012).
- **`eulerlab.master.registry`** — time-versioned attributes. `at(as_of)`
  returns what was true then. Resolution is bounded by the observation window,
  so a delisted instrument stops claiming its ticker.
- **`eulerlab.master.build`** — folds bhavcopy into the registry, streaming
  from B2 rather than restoring to disk.
- **`eulerlab.master.symbology`** — 580 renames derived from ISIN continuity,
  written to `config/symbol_renames.json`.
- **`eulerlab.master.succession`** — four relationship kinds with cited terms
  (ADR-013): rename, merger, demerger, cancellation.

## Sprint 3 — what is NOT built

- **F&O instrument keys.** Derivatives have no ISIN in the bhavcopy and need a
  composite key (symbol, expiry, strike, right). Not started.
- **Trading calendar from evidence.** Not started.
- **`make check-master`.** The sprint's acceptance command does not exist yet.
- **Lot-size history.** The registry has the field and the builder populates it
  from `NewBrdLotQty`, but it is unverified against a known past value.

## Data issues fixed this session

| Issue | Resolution |
|---|---|
| 7 participant-OI days missing | Files existed; transient failures. All recovered, zero gaps |
| 34 minute symbols unresolved | 21 renames auto-resolved from ISIN continuity and refetched |
| 4 more "delisted" | **Were never delisted** — BE-series lookup bug in `parse_instruments`. Fixed, fetched |
| 5 successions | Recorded with cited terms and ratios |
| 7,304 spurious renames | Fund units were merging under a shared issuer prefix. Fixed → 580 |

## Known issues and open questions

- **`TATACOFFEE` succession deliberately unrecorded.** Sources give 3:10 and
  14:55 for a demerger-plus-amalgamation. Guessing would misprice every
  position carried across it.
- **`DHANI`, `JPASSOCIAT` unresolved.** Not researched individually.
- **Three datasets are collected against site terms**, knowingly and on the
  record: NSE (ADR-006), Trendlyne (ADR-009, not built), screener.in (ADR-011).
- **No consensus/forecast data exists** for Indian macro or earnings, so
  "surprise" is not computable (research notes 004, 005).
- **Most market-structure facts remain unverified** — see `docs/ASSUMPTIONS.md`.
- **NSE corporate-actions feed found** (research note 008): systematic for
  dividends/splits/bonus/rights keyed by ISIN, and **silent on mergers that
  delist the target**. Sprint 5 should use it.

## Money

| Cost | Amount | Status |
|---|---|---|
| Zerodha Kite Connect | ₹500/mo | Active |
| Backblaze B2 | under ₹100/mo | Active, bucket `eulerdata` |
| Mumbai VPS | ₹500–900/mo | Deferred — only the options recorder needs it |

**Run rate: ~₹600/mo.**

## Resuming in a new session

Read `CLAUDE.md`, `STATE.md`, `TASKS.md`. Then
`docs/RUNBOOKS/resuming-in-a-new-session.md` explains the handoff, and
`docs/ARCHITECTURE.md` has diagrams of what is built.

**The Kite token expires at 06:00 IST daily** — `make kite-login` before any
Kite work. Background jobs do not survive a session; check with
`pgrep -fl "backfill_|sync_"`.
