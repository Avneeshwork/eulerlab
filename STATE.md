# STATE — where this project is right now

**Sprint:** 28 — the order path: OMS, EMS, reconciler, kill switches, paper trading
**Status:** COMPLETE — sprints 0-28 all done, every code sprint in the build plan
**Next:** Sprint 29-30 compliance, which is the operator's work, not a coding task

Sprints 19-28 were built as one block: paper trading cannot be built without an
OMS, and an OMS with nothing driving it cannot be tested end to end. Sprints
29-30 need a static IP registered with the broker, confirmation of the algo
framework, and a CA review of F&O business income and STCG/LTCG treatment —
none of which is code. Then Sprint 31, first micro-live capital at 1-2%.

*Last updated: 2026-08-20. One page, always current. If it is not written here
or in `TASKS.md`, it did not happen.*

---

## START HERE IF YOU ARE A NEW SESSION

Read `CLAUDE.md`, then this file, then `TASKS.md`. Then:

**1. Prove the repository is healthy before believing anything in it.**

```bash
make verify
```
Expect **7 of 7 green and ~922 tests**. Two rows are gates rather than
hygiene, and both block everything downstream if red:

- **`engine`** — the backtester self-tests. If red, no strategy number can be
  believed.
- **`chaos`** — the OMS crash-recovery scenarios. If red, no order can be
  believed. Two of its eleven scenarios `SIGKILL` a real subprocess mid-order.

**2. `mandate.yaml` and `src/eulerlab/gates.py` are OPERATOR-OWNED.** Sprint 14
wrote them once. From here: propose changes in a review, never edit them
without an explicit instruction in that session. `mandate.yaml` holds every
threshold and no logic; `gates.py` holds logic and no thresholds, and a test
enforces that.

**3. There is no code sprint left to start.** Sprints 29-30 are compliance
and belong to the operator: registering a static IP, confirming the broker's
algo framework, wiring `algo_id` end to end, and a CA review of F&O business
income and STCG/LTCG treatment. See `docs/COMPLIANCE_DEFERRED.md`. Do not
invent progress on these — none of them is a coding task.

**The two things I can do on the operator's word** are T-1317 (re-run Sprint
8's IC sweep on corrected prices, which is cheap and settles whether H-0002 is
worth registering) and T-1407 (exercise the gate's PROMOTE path, which has
never been taken).

**Before generating hypotheses, run `make scout PROPOSE=n`.** Every one raises
the statistical bar for all of them. At 17 logged trials a candidate must
already beat Sharpe 1.83 from pure noise; the best this project has produced is
1.27. The guardrail is not the gate — the gate sees one candidate at a time —
it is the counter, which sees the whole search (ADR-026).

**4. Two decisions waiting on the operator:** T-1408, formally mark H-0001
killed — the gate has already returned KILL and the ledger records it. And
T-1407, exercise the gate's PROMOTE path with a known-good synthetic
candidate, because it has never promoted anything and a check that has only
fired one way is half-tested.

**Costly commands, so you do not run them by accident:**

| command | cost |
|---|---|
| `make validate H=H-0001` | ~40 min, 150 backtests (T-1319 would parallelise) |
| `make build-panel FROM=2015-01-01` | ~2,900 B2 downloads; the panel is already built |
| `make build-factors` | ~2,121 B2 downloads; already built and cached |

Backblaze allows **2,500 downloads/day free**. Everything data-related is
already downloaded and cached — see `docs/RUNBOOKS/b2-transaction-cap.md`
before starting anything that fetches.

## The order path is live in paper mode only

**There is no live broker adapter and nothing here has met a real market.**
The only adapter is `PaperBroker`, a simulator that fills at a price we hand
it with slippage we choose (S-015). What Sprints 19-28 verify is that the
order path, the crash recovery and the accounting are correct — not anything
about execution.

Three properties are worth knowing before touching this code:

- **Intent is fsynced before the network call** (ADR-029). Reversing those two
  lines is the one change that makes a crash unrecoverable, because an order at
  the exchange with no local record is invisible to reconciliation forever.
- **`UNKNOWN` is only left by asking the broker** (ADR-028). There is no event
  in the transition table that means "give up and assume", and a test asserts
  that over the whole table. Do not add one.
- **The reconciler never places an order** (ADR-030). It corrects our record.
  A break means we do not know what happened, and trading on that doubles the
  position exactly when the cause is a fill we missed.

Paper trading is `event_driven.run` with a different `Executor` plugged in,
not a second loop (ADR-031). A frictionless paper run reproduces the backtest
**exactly** — measured on the real panel over 546 days and 829 trades, the gap
is 0.00. If that ever becomes non-zero, the two paths have drifted and that is
the thing to fix, not to explain.

```bash
make chaos                                   # 11 scenarios, seconds
make attribution FRICTIONLESS=1 DAYS=800     # gap must be exactly 0.00, ~6 min
make reconcile-book                          # our positions vs the broker's
make kill-status                             # is trading stopped, and why
```

## Derived artefacts: what exists locally, and how to rebuild it

All of `data/` is gitignored, so a fresh clone has **none** of this. Rebuilding
costs Backblaze downloads against a 2,500/day cap, so check before deleting
anything.

| file | size | rebuild | cost |
|---|---|---|---|
| `price_panel.jsonl` | 540 MB | `make build-panel FROM=2015-01-01` | ~2,900 downloads, ~25 min |
| `price_factors.jsonl` | 0.1 MB | `make build-factors` | ~2,121 downloads, ~4 min |
| `total_return_factors.jsonl` | 2.3 MB | same command | — |
| `close_index.jsonl` | 0.8 MB | same command (its cache) | — |
| `trial_ledger.jsonl` | small | **never rebuild** | hash-chained; regenerating destroys the audit trail |
| `evidence/H-0001.json` | small | `make validate H=H-0001` | ~40 min |

`trial_ledger.jsonl` is the one file that must not be recreated. It is the
denominator of every multiple-testing correction, it is hash-chained so edits
are detectable, and `CLAUDE.md` says never reset it. If it is missing, say so
rather than starting a fresh one — a chain that begins late understates the
trial count in the flattering direction.

## What is known to be WRONG or unverified

Read this before trusting any number produced before today.

- **Sprint 8's IC figures were computed on raw, unadjusted prices** and have
  not been re-run (T-1317). Its conclusion that "ten features are really three
  findings" also used the 3-year panel, not the 11-year one.
- **Sprint 10's review states a conclusion its own data does not support.**
  It is corrected in place at the top of the file; the body is left as
  written.
- **The cost model has never met a real contract note** (T-906). Every rate
  comes from a secondary source (A-016). This is the cheapest verification
  available in the project and it needs the operator: copy
  `config/contract_notes.example.json` to `config/contract_notes.json` and
  fill in real figures.
- **Excess kurtosis of ~155 remains** on one configuration after the
  price-adjustment fix, so the fat tails are not fully explained (T-1310).
- **Market impact is not modelled at all** (T-907). Any result involving a
  thin name is optimistic.
- **The reality-gap residual is an identity, not a measurement** (S-018).
  Both books are ours, so the decomposition closes to zero by arithmetic. The
  build plan's "residual under 10%" is about explaining a *live* shortfall and
  cannot exist before Sprint 29. Do not quote the residual as evidence that
  execution is understood.
- **The paper cost figure is our own model on both sides** (S-017), so the
  "cost model error" term of the reality gap is structurally zero. T-906 is
  what would give it meaning.
- **The kill-switch limits are round numbers, not measured** (A-018, S-020).
  They fire correctly at the levels configured; whether those levels are right
  is unknown until there are a few weeks of paper P&L to look at.
- **`ACKNOWLEDGED` and `PARTIALLY_FILLED` have never been produced by a real
  venue** (S-016). They are in the state machine and unit-tested; the paper
  broker fills everything instantly and completely.

---

## Sprints 16-18 — what is built

```
card -> critic -> codegen -> [operator registers] -> battery -> gate
       free      free                               ~40 min    seconds
```

- **`research.codegen`** — composes vetted primitives, **never writes Python**
  (ADR-027). Executing generated source would discard Sprint 4's firewall.
  The cost: no novel strategy shapes without a hand-written primitive.
- **`research.critic`** — objects *before* a trial is spent, reading only the
  card and the ledger. No check consults price data: peeking at performance
  then deciding whether to "officially" test is how a trial gets laundered.
  **Advisory only** — it cannot kill anything.
- **`research.orchestrator`** — `make research`, the weekly report. Gate
  verdicts are read from the ledger so the report cannot drift from evidence.

**The loop stops at registration.** An agent that could originate a hypothesis
*and* decide it was worth testing would be selecting on its own output.

Note for honesty: the critic raised **no blocker** on H-0001, which the gate
then killed (T-1608). One data point, in the unhelpful direction.

## Sprint 15 — what is built

- **`eulerlab.research.budget`** — `make scout PROPOSE=n` prices a search
  before it runs and refuses one the history could not support afterwards.
- **`eulerlab.research.card`** — hypothesis cards as specs. Red flags that are
  hedges ("markets can change") are rejected; a card must name a number, a
  mechanism, or a finding from this project. Cards never overwrite and ids are
  never recycled, because the trial ledger refers to them.
- **`hypotheses/H-0002.yaml`** — low-volatility anomaly, drafted from real NSE
  literature (research note 014). **Draft, not registered.** Its own red flags
  argue against it: the supporting Sprint 8 t-statistic of +5.78 came from raw
  prices on a 3-year panel and cannot be cited (T-1317).

## Sprint 14 — what is built

- **`mandate.yaml`** — **operator-owned.** Every threshold, no logic.
- **`src/eulerlab/gates.py`** — **operator-owned.** All logic, no thresholds; a
  test asserts no threshold literal appears in it (ADR-025).
- **`make gate H=H-0001`** — PROMOTE or KILL with every reason.
- **`make gate-acceptance`** — three deliberately overfit strategies; all must
  be killed, and are.

**The gate's first act was to kill H-0001**: DSR 0.086 against a 0.95 bar, PBO
60% against 25%, and no stress data in its pack. The project's only candidate
is dead, and `CLAUDE.md` says it is not tuned and resubmitted.

**Honest weakness found by the acceptance test itself:** `RegimeFit`, built to
fail the regime check, *passed* it at 76% retained. The stress splits at the
panel midpoint (2020-10-23) while the defect starts 2021-01-01, so three
months of live signal sit in the half meant to be broken. It was killed by the
statistical rules instead. Recorded as T-1404 rather than patched, because
fixing a test after seeing what slipped past it is how a gate gets tuned to
the cases in front of it.

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

## Follow-up: positions were marked at raw prices

Chasing Sprint 13's kurtosis red flag found a bug that matters more than the
sprint did. **The engines valued holdings using unadjusted prices.** VIVIDHA
prints 1,290.55 and then 140.75 the next day on an 11:1 action; a holder's
share count rises by the same factor and they lose nothing, but the engine
holds a fixed integer, so it booked an 89% loss. Every corporate action in a
held name produced phantom P&L.

Three things were wrong and all are fixed:

1. **The panel claimed to be adjusted and was not.** It called
   `factor_as_of(as_of=<the row's day>, price_date=<the same day>)`, whose two
   conditions are mutually exclusive, so the divisor was always 1.0. Measured:
   TCS on 2018-01-15 got 1.000 where 2.000 is correct.
2. **A static panel cannot hold point-in-time adjusted prices** — the right
   adjustment depends on the date you stand on. Signals now adjust per
   decision date, in `MarketView`.
3. **Marking needs the opposite**: a *consistent* series, or a position's
   value jumps when the adjustment updates rather than on the ex-date. Money
   uses a uniformly back-adjusted series; signals use point-in-time.

A guard now refuses a panel with no instrument key, because the original bug
was a silent no-op and would otherwise return the same way.

**Every figure was re-run on corrected prices.** Momentum now shows +16.8%
annualised against buy-and-hold's +4.6%, and the battery's verdict is
unchanged — PBO went 53.3% to **60.0%**. Fixing the data made the strategy
look better and no more distinguishable from luck, which is the point.

## Sprint 13 — what is built

- **`eulerlab.validation.cpcv`** — purged, embargoed, combinatorial CV. 15
  paths, with the no-leakage property asserted on every one.
- **`eulerlab.validation.statistics`** — Deflated Sharpe, PBO, MinBTL. Every
  one takes the trial count as a **required** argument; defaulting it is the
  most flattering silent assumption available.
- **`eulerlab.validation.ledger`** — hash-chained trial log. The battery
  **refuses to print anything** if the chain is broken (ADR-023).
- **`eulerlab.validation.holdout`** — 2025+ reserved and never read; the panel
  is truncated once at the top so nothing downstream can peek.
- **`hypotheses/H-0001.yaml`** — claim, configurations and red flags fixed
  before the evidence.
- **`eulerlab.validation.stress`** — costs, signal staleness, concentration,
  regime. Robust to 5x costs and to dropping its best five names; **not robust
  across regimes: Sharpe 0.49 in 2015-2020 against 1.48 in 2020-2026**, which
  corroborates the 60% PBO.
- **`make validate H=H-0001`** — hash-signed evidence pack, stress tests included.

### H-0001 does not survive

| | |
|---|---|
| **PBO** | **53.3%** — worse than a coin flip |
| **Deflated Sharpe** | ≤ 0.021 (0.95 is the bar) |
| best real Sharpe | 1.01 |
| expected best from **13 worthless strategies** | **1.70** |

The best real result is *below* what searching this hard would produce from
pure noise. Sprint 10 said momentum was no good, Sprint 11 said it was
excellent, Sprint 13 says it is indistinguishable from luck. Confidence should
track the strength of the test, not the appeal of the result.

**Red flag found late:** two configurations show excess kurtosis of **+101 and
+161**. A Sharpe ratio on tails that fat is close to meaningless. T-1310.

## Sprint 12 — what is built

- **`eulerlab.backtest.selftest`** / **`make test-engine`** — ten checks on
  synthetic worlds whose answer is known by construction. Now inside
  `make verify`, because a gate you must remember is one that gets skipped.
- **`tests/test_engine_selftests.py`** — a mutation suite that breaks the
  engine on purpose and asserts the gate goes red.

### The mutation suite found a hole in the gate

All ten checks passed first time, which is when a gate is least trustworthy.
Doubling every fee **still passed** `zero alpha = exact cost drag`: the cash
deduction and the recorded fee both doubled, so `loss == costs` held. The books
were self-consistent and completely wrong. Fixed by adding `costs match the
cost model`, which recomputes every fee through a path the engine does not
share (ADR-022).

### And a flaw in Sprint 8's work

The IC harness's null anchor used `hash(symbol) % 997`. Python randomises
string hashing per process, so it was non-deterministic; worse, a
**constant-per-symbol label is not a null** — in a fixed panel some symbols
persistently out-drift others, so a fixed ordering scores a real IC, measured
at **t = 4.7**. The null is now re-drawn each period, and a second test records
the trap so it is not reintroduced.

## Sprint 11 — what is built

- **`eulerlab.backtest.events`** — Order, Fill, Rejection, Position, Portfolio.
  Deterministic client order ids and `algo_id` present from day one.
- **`eulerlab.backtest.event_driven`** — Tier B. The **same `Strategy` object**
  Tier A runs, unadapted.
- **`make backtest`** — runs Tier B and reconciles against Tier A every time.

### The two engines agree to machine epsilon

Over 1,587 days the curves differ by **8.05e-16 relative**. That makes
CLAUDE.md's "one interface" rule an executable claim. Tier B also records what
Tier A can only skip: on the momentum run, **2,837 orders → 2,129 fills + 708
rejections**.

### Sprint 10's conclusion was wrong, and is corrected

The panel now covers 2015-2026 rather than 2023-2026:

| window | | annualised | max drawdown |
|---|---|---|---|
| 2023-2026 | buy & hold | +10.1% | -20.0% |
| | momentum_12_1 | +3.0% | -42.2% |
| **2016-2026** | buy & hold | +7.3% | -41.9% |
| | **momentum_12_1** | **+18.4%** | **-31.6%** |

Sprint 10 said "a strong IC is not a strategy". Over eleven years momentum
beats buy-and-hold by eleven points a year with a *smaller* drawdown. Its own
review had listed "three years is one regime" as an unverified limitation and
then drew a headline that depended on it. Corrected in place.

**Consequence: every Sprint 8 conclusion used the 3-year panel** and should be
re-run (T-1107).

## Sprint 10 — what is built

- **`eulerlab.backtest.strategy`** — the one `Strategy` interface. A strategy
  is handed a `MarketView` ending at its decision date and returns target
  weights. It cannot fetch data, place orders, or express a cost, so there is
  exactly one cost path *structurally* (ADR-021).
- **`eulerlab.backtest.vector`** — Tier A. Next-bar fills, costs from Sprint 9,
  and a published list of what it cannot model.
- **`make backtest-fast`** — ~25s, `COMPARE=1` runs both cost modes.

### The finding: a strong IC is not a strategy

| | annualised | max drawdown |
|---|---|---|
| buy and hold (top 30 liquid) | **+10.1%** | **-20.0%** |
| momentum_12_1 (IC t=+5.40) | +3.0% | -42.2% |
| same, liquidity-screened | +1.2% | -38.2% |

IC ranks the whole cross-section equally, including names nobody could own —
the unfiltered top 30 held **SPYL on ₹49,839 of daily turnover**. A portfolio
has to actually hold things.

### The bug, caught by disbelief rather than by a test

The first run showed -13.1% with a **-50% drawdown**, implausible for a
long-only book in a rising market. Holdings whose instrument did not print
that day were valued at **nothing** and restored the next day; 31 of 400
symbols have such gaps. Now marked at last known price, while still refusing
to *trade* an instrument that did not print. Corrected return: +7.8%.

## Sprint 9 — what is built

- **`eulerlab.costs.schedule`** — rates keyed by effective date, because they
  changed inside our backtest window: futures STT 0.0125% → 0.02% → 0.05%.
  Refuses to answer for a date before the schedule rather than silently using
  later rates (ADR-020).
- **`eulerlab.costs.model`** — itemised per leg, in `Decimal`. STT sell-side
  for intraday/futures, stamp duty buy-side only, GST on brokerage plus
  exchange charges rather than turnover.
- **`make check-costs`** — 4 green, 1 PARTIAL awaiting real contract notes.

### A-005 was wrong, and used to be right

The playbook said STT on option exercise is charged on notional. True until
2019-08-31, false since — it is charged on **intrinsic value** now. On the
published example that is **₹3.75 versus ₹1,084.38** on a ₹2,500 profit, 43%
of it. Both rules are implemented and selected by trade date, because the old
one governs 2015 to mid-2019 of our own history.

**What Sprint 9 needs from the operator:** real contract notes. The gate is
written and gitignored at `config/contract_notes.json`; five would make it
meaningful. Every rate currently comes from secondary sources (A-016) because
NSE's own pages would not fetch.

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
