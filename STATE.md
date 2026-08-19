# STATE — where this project is right now

**Sprint:** 8 — feature library and IC harness
**Status:** COMPLETE
**Next:** Sprint 9 — cost model (brokerage, STT, stamp duty, GST, impact)

*Last updated: 2026-08-19 21:40 IST. One page, always current. If it is not
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

## Sprint 8 — what is built

The first sprint about *prediction* rather than *correctness*.

- **`eulerlab.features.panel`** — adjusted price panel, cached and resumable.
  892 days, 3,331 symbols, 2.0M rows. Joins factors on `InstrumentId`; the
  ticker-vs-ISIN version would have applied **no adjustment at all** and said
  nothing.
- **`eulerlab.features.library`** — ten seed features, each a pure function of
  one symbol's own history, so a feature physically cannot see past its
  evaluation date. Signs normalised so higher is always better.
- **`eulerlab.features.ic`** — rank IC through the firewall. Calibrated at
  both ends: an oracle feature that *is* the forward return scores exactly
  1.0, and noise scores ~0. Without those anchors a middle number is
  meaningless.
- **`eulerlab.features.trials`** — the append-only trial counter, started here
  rather than at Sprint 13 because a count that begins late undercounts in the
  flattering direction (ADR-019).
- **`make ic FEATURE=...`** — tear sheet in ~75s.

**Result:** `momentum_12_1` scores t=+5.40, positive in all three years. That
is a **sanity check, not a discovery** — 12-month momentum is among the most
documented effects in global equities, so finding it means the harness works.
The panel covers 2023-2026, which is almost entirely a bull market, and the
overlapping cross-sections inflate the t-statistic. Nothing here is evidence
of tradeable edge until it meets Sprint 9's costs.

**A pattern worth naming**, now that it has appeared three times: MAD over
standard deviation (ADR-017), Theil-Sen over least squares (ADR-018), and rank
over Pearson (ADR-019). Every estimator in this codebase that touches market
data needs a non-zero breakdown point, because the data reliably contains
points that would otherwise dominate it.

## Sprint 7 — what is built

Runs on **EOD F&O bhavcopy chains**, not the intraday chains the build plan
assumed — Sprint 2's recorder has still never run (ADR-018).

- **`eulerlab.options.chain`** — one day's chain per (underlying, expiry) from
  either archive era, reusing Sprint 3's contract identity unchanged. Every
  quote carries `traded`, because NSE computes a settlement price for strikes
  that never traded and a violation there measures NSE's model, not the market.
- **`eulerlab.options.arbitrage`** — put-call parity, strike monotonicity,
  butterfly convexity, intrinsic bounds, calendar inversion. Hard inequalities
  rather than tuned thresholds. The forward *and* discount factor are implied
  from the chain, so no risk-free rate is invented.
- **`eulerlab.options.iv`** — Black-76 with bisection. Returns None rather
  than clamping when no volatility fits, because that is itself the finding.
- **`make quality-options`**.

### First contact with real data

The cap lifted, so all three queued runs executed. What they showed:

- **S-012 rebuilt: coverage 78.1% → 98.1%**, recovering **3,073 dividend
  factors** the raw-ISIN join had silently dropped. `make check-adjust` is now
  **7/7 green**, and its series check validates **40 of 40 real 1:1 bonuses
  showing the expected ~2x raw price drop**.
- **The spike threshold was badly wrong and is now measured.** 5.0 flagged
  **1.042% of 632,133 real symbol-days** — a z of 5.1 is merely the *99th
  percentile of ordinary trading*, because equity returns are fat-tailed.
  Recalibrated to 15.0 (p99.9). Total findings fell 6,892 → 740.
- **The options forward fit is validated against reality**: the implied
  forward landed **2.5 points from the actual futures price on 24,400**
  (0.01%). So the 56 lower-bound ERRORs are real stale settlement marks on
  deep-ITM strikes, not an artefact of my own fit.
- **The quality engine found a real gap in our own data (S-013).** GROWWGOLD,
  BANKNIFTY1 and CONS all fell ~90.1% on 2026-02-27 — a 1:10 unit split — and
  **none appear in the corporate-actions feed at all**, because it is queried
  with `index=equities`. Any ETF backtest would see a phantom -90% crash.

### The defect this sprint found

The forward fit is the benchmark every parity and intrinsic check measures
against. With ordinary least squares, one call planted at ₹1 against a ₹1,000
intrinsic skewed the fit until the discount factor left its plausible range —
so the fit returned None and the check reported **nothing at all**. The
corruption hid by destroying the instrument meant to detect it.

This is exactly the standard-deviation failure from Sprint 6 wearing different
clothes, and it takes the same answer: Theil-Sen, whose breakdown point is
29% rather than zero.

## Sprint 6 — what is built

- **`eulerlab.quality.robust`** — MAD-based outlier detection. Two measured
  facts drove it (ADR-017, research note 011): a 3-sigma rule **cannot fire**
  on a series of 10 points, because the largest achievable z-score is
  `(n-1)/sqrt(n)` = 2.85; and a stdev score for the same outlier varies 5x
  with history length while the robust score does not move at all.
- **`eulerlab.quality.manifest_checks`** — coverage, gaps, staleness,
  duplicate keys, empty files. **Zero B2 downloads**, so these run under the
  daily cap.
- **`eulerlab.quality.row_checks`** — OHLC invariants (ERROR, absolute),
  turnover consistency, extreme moves, MAD spikes, stale-price runs.
- **`eulerlab.quality.reconcile`** — bhavcopy close vs Kite's aggregated
  minute bar. Built and tested; **not yet run** against real data.
- **`make quality`** — free checks. **`make quality ROWS=n`** adds row checks
  at one B2 download per file.

### What it found in its own first run

Three defects in the engine itself, each caught by a test rather than review:
a blanket suppression that hid the 3 real S-007 gaps along with the 1,052
benign ones; an extreme-move threshold of 0.60 that could not catch the
unadjusted 1:1 bonus its own docstring named (-50%); and MAD collapsing to
zero on an imbalanced bimodal series, flagging 9 of 19 rows at infinite score.

In the data: 2 byte-identical re-landings from the S-009 probe. The check now
splits on hash — identical bytes INFO, differing bytes under one key ERROR.

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
  field was null on every row checked). Covers bonus, split, **rights**
  (`P/TERP`, research note 010) and dividends. A 1:1 TCS bonus confirmed
  against its real ISIN; the rights formula validated against Reliance's 2020
  issue.
- **`eulerlab.corp_actions.prices`** — the close-price index, streaming cash
  bhavcopy from B2. Joins on `InstrumentId`, never the raw ISIN, and caches
  every fetched day to disk so the expensive pull happens once.
- **`make build-factors`** — builds and persists both factor series. One full
  run completed (2,121 files, 3m30s).
- **`make check-adjust`** — the build plan's acceptance gate for this sprint.
  Every factor is **recomputed independently from the raw feed text** by
  arithmetic that shares no code with the engine, so a ratio read backwards is
  caught rather than confirmed. 6 checks green; the price-series reproduction
  is SKIP until S-012 supplies the close-price cache.

### Two defects this sprint found

**The ISIN join was wrong, and it failed quietly.** The corporate-actions feed
and the bhavcopy disagree about trailing ISIN serials for the same company on
the same day — on 2017-11-21 the feed called Aurobindo Pharma `INE406A01029`
while the bhavcopy called it `INE406A01037`. Joining on the full string lost
**21.9% of all price lookups**, surfacing as a plausible-looking "78% coverage"
rather than an error. Fixed by joining on `InstrumentId` (ADR-012), which is
precisely what that id exists for, and regression-tested.

**One full build costs 85% of a day's B2 free tier.** 2,121 downloads against
a 2,500/day Class B cap. Running the build twice in one session exhausted it
outright. The close-price index is now cached and resumable, so the pull
happens once ever — see `docs/RUNBOOKS/b2-transaction-cap.md`.

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

### First contact with real data

The cap lifted, so all three queued runs executed. What they showed:

- **S-012 rebuilt: coverage 78.1% → 98.1%**, recovering **3,073 dividend
  factors** the raw-ISIN join had silently dropped. `make check-adjust` is now
  **7/7 green**, and its series check validates **40 of 40 real 1:1 bonuses
  showing the expected ~2x raw price drop**.
- **The spike threshold was badly wrong and is now measured.** 5.0 flagged
  **1.042% of 632,133 real symbol-days** — a z of 5.1 is merely the *99th
  percentile of ordinary trading*, because equity returns are fat-tailed.
  Recalibrated to 15.0 (p99.9). Total findings fell 6,892 → 740.
- **The options forward fit is validated against reality**: the implied
  forward landed **2.5 points from the actual futures price on 24,400**
  (0.01%). So the 56 lower-bound ERRORs are real stale settlement marks on
  deep-ITM strikes, not an artefact of my own fit.
- **The quality engine found a real gap in our own data (S-013).** GROWWGOLD,
  BANKNIFTY1 and CONS all fell ~90.1% on 2026-02-27 — a 1:10 unit split — and
  **none appear in the corporate-actions feed at all**, because it is queried
  with `index=equities`. Any ETF backtest would see a phantom -90% crash.

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
- **The persisted factor files must be rebuilt** (S-012). The one completed
  full run used the defective raw-ISIN join. The output was deleted rather
  than left on disk, so nothing can read an incomplete factor set. Re-running
  is blocked until the B2 daily cap resets: `make build-factors`.
- **The rights formula came from a broker's summary, not the NSE circular**
  (A-015). Cross-checked algebraically against the standard TERP identity and
  validated on Reliance's 2020 issue, so confidence is medium-high, but the
  primary source has not been read.

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
