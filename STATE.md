# STATE — where this project is right now

**Sprint:** 5 — corporate actions and adjustment engine
**Status:** COMPLETE
**Next:** Sprint 6 — TBD

*Last updated: 2026-08-19 12:10 IST. One page, always current. If it is not
written here or in `TASKS.md`, it did not happen.*

---

## Datasets — what exists

| Dataset | State | Coverage |
|---|---|---|
| NSE EOD bhavcopy (cash + F&O) | **COMPLETE** | 5,737 files, 2015-01-01 → 2026-08-17. One known source gap: no F&O for 2021-03-30 (S-009) |
| Participant-wise F&O OI | **COMPLETE** | 1,639 days, 2020 → today, **zero gaps** |
| Kite 1-minute bars | **COMPLETE** | 13,499 chunks, 420 symbols, **184M bars**, 5 years |
| screener.in fundamentals | **COMPLETE** | 2,352 companies (328 no data, 22 404s — mostly ETFs) |
| NSE corporate actions | **COMPLETE** | 12 years, 2015–2026, 25,713 actions, 94.3% parsed |
| Options chains / tick data | **NOT STARTED** | deferred by the operator three times |

Everything is mirrored to Backblaze B2 bucket `eulerdata`. Local disk holds a
working subset only; files are pruned after B2 confirms them (ADR-010) and
restored with `make restore-local`.

## Sprint 5 — what is built

- **`eulerlab.corp_actions.feed`** — backfills NSE's corporate-actions API
  (research note 008), one file per year. Verified the date parameters are
  honoured (unlike the FII/DII feed) and no pagination limit exists at this
  scale (research note 009). Run for real: 12 years landed, synced to B2.
- **`eulerlab.corp_actions.parse`** — turns free-text `subject` strings into
  typed dividend/bonus/split/rights components. Handles compound subjects
  ("Bonus 1:1 / Face Value Split..."), NSE's own typos (`"62..50"`, `"Rs-
  70"`), and never guesses a ratio it cannot read — 94.3% of price-relevant
  clauses parsed on the real 25,713-action dataset; the rest are genuinely
  amount-less announcements ("Interest Payment") with nothing to extract.
- **`eulerlab.corp_actions.adjust`** — back-adjustment factors built through
  Sprint 4's `BitemporalStore`, so `factor_as_of` cannot include an action
  the caller could not yet have known (ADR-016: knowledge_time is
  conservatively each action's own ex-date, since the feed's announcement-date
  field was null on every row checked). Price-adjustment (bonus + split) run
  against the full real dataset; a 1:1 TCS bonus confirmed against its real
  ISIN. Total-return (dividends reinvested) is built and unit-tested but its
  full 11-year run needs a close-price index this session did not build
  (S-010).
- **`eulerlab.corp_actions.prices`** — the close-price index for the dividend
  factor, streaming cash bhavcopy from B2 the same way `build_master` does.

## Sprint 4 — what is built

- **`eulerlab.bitemporal.store`** — the research read API. `as_of` is required
  and keyword-only, filtering happens inside `query`, and no public reader
  returns unfiltered rows. `Record` is frozen and both timestamps must be
  tz-aware (ADR-014).
- **`eulerlab.bitemporal.provenance`** — separates *when a fact became
  knowable* from *when we downloaded it*. These were the same field until this
  sprint, and the gap between them has a median of 1,820 days (ADR-015).
- **`eulerlab.bitemporal.universe`** — refuses a universe list on any date
  before the list was computed. Closes the survivorship half of the firewall.
- **`make test-lookahead`** — 36 adversarial tests. **`make provenance`** — the
  vintage table.

### The defect this sprint found in our own data

Every manifest row's `knowledge_time` holds the **download** time, not the
publication time. Filtering a backtest on it returns zero rows for all eleven
years — and the tempting fix for an empty frame is to loosen the filter, which
is a leak. Now derived from the trade date instead, with the download time kept
as `receipt_time` for pipeline auditing.

Only **4 of 7,378** NSE files are true point-in-time captures. The rest are
`Vintage.FINAL`: correct timing, but the content is whatever the archive serves
today. If NSE ever corrected a file, we hold the correction and no trace of the
original. Unrecoverable, so it is carried in the type.

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

- **`eulerlab.master.derivatives`** — the F&O composite key (underlying,
  expiry, strike, right), since derivatives carry no ISIN in either era.
  Validated on real files: 28,984 contracts in 2015 and 35,089 in 2026, zero
  unparsed rows and zero duplicate keys.
- **`make check-master`** — 5 acceptance checks, all green.

- **`eulerlab.master.calendar`** — trading days from evidence, never a weekday
  rule. Built from the manifest: 2,869 trading days, zero long gaps, and it
  correctly flags 2021-03-30 as SUSPECT (cash traded, F&O did not) rather than
  guessing whether that was a holiday or a missing file.
- **`eulerlab.master.contracts`** — derivative registry with time-versioned lot
  sizes. Built from 140 monthly F&O snapshots: 2.29M contracts, 385
  underlyings, 5.7M contract-days.

- **`eulerlab.master.store`** — the master persisted as diffable JSON with a
  build stamp. Deterministic: two builds of the same data are byte-identical.
- **`eulerlab.master.broker_map`** — internal id ↔ Kite token, resolved through
  the master *as of a date* because tokens are reused. Filters bonds and ETF
  NAV feeds, which Kite files under `instrument_type=EQ`.
- **`make build-master`** / **`make check-master`** — build and verify.

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
- **All 34 minute-bar symbols are now resolved.** `DHANI` merged into
  `IBULLSLTD` (terms not published — recorded as `terms_pending`), and
  `JPASSOCIAT` was delisted in insolvency with no successor.
- **Three datasets are collected against site terms**, knowingly and on the
  record: NSE (ADR-006), Trendlyne (ADR-009, not built), screener.in (ADR-011).
- **No consensus/forecast data exists** for Indian macro or earnings, so
  "surprise" is not computable (research notes 004, 005).
- **Most market-structure facts remain unverified** — see `docs/ASSUMPTIONS.md`.
- **The publication hour is assumed, not sourced** (A-014). Deliberately late
  at 20:00 IST so the error withholds data rather than leaking it; participant
  OI is bounded to 19:09 by one same-day capture. Daily strategies are
  unaffected either way.
- **NSE corporate-actions feed ingested and wired to the adjustment engine**
  (Sprint 5). Still **silent on mergers that delist the target** — Sprint 3's
  succession model remains the source of truth there.
- **Rights-issue price effect is parsed but not adjusted** (S-011): the
  correct formula needs the issue price, not just the ratio.
- **Total-return factor build for the full 11-year history was not run**
  (S-010): correctness is unit-tested; the real run needs a ~2.2 GB
  close-price index streamed from B2.

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
