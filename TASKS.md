# TASKS — the ledger

Every task, its status, and the command that proves it. Statuses:
**TODO** · **DOING** · **DONE** · **BLOCKED** · **KILLED**

Sprints 0–14 are seeded from `docs/AI_BUILD_PLAN.md` §6 and
`docs/sprint_01_kickoff.md`. Sprints 15+ are planned three ahead, per the build
plan — they are listed here as scope only, not as tasks.

---

## Tweezer Bottom — intraday candlestick strategy (2026-08-20)

Operator-supplied rules. Verify: `uv run pytest tests/test_intraday_tweezer.py`

| ID | Task | Status |
|---|---|---|
| T-3201 | Indicators written by hand, not `pandas_ta` | DONE — no new dependency; every primitive tested against a hand-computed value |
| T-3202 | Wilder smoothing kept distinct from an EMA | DONE — 1/n not 2/(n+1); a test pins it |
| T-3203 | Pattern detector, Steps 1-8 exactly | DONE — `intraday/tweezer.py` |
| T-3204 | Bracket executor, Steps 9-10 | DONE — stop-entry, TP1/TP2, breakeven, trailing, session close |
| T-3205 | Ambiguous bars resolved against us | DONE — a bar holding both stop and target takes the STOP |
| T-3206 | Rejections name the rule and the value | DONE — "no trade" and "ADX was 51" are different facts |
| T-3207 | Panel carries OHLC | DONE — optional, falls back to a flat bar (S-024) |
| T-3208 | ~~Never run on real data~~ | DONE — reads B2 directly; `make tweezer` |
| T-3211 | `restore_local` cannot see minute data | DONE — it walks the NSE manifest, which never covered `kite_minute`; `intraday/store.py` reads B2 directly |
| T-3212 | **The setup is extremely rare** | OPEN — 2 setups in 136,740 candles (3 symbols, 6 months). 0.15% low tolerance on minute bars is very tight. T-3214 makes scanning a wider universe possible; the wider run itself has not been executed, so this is still evidence-free |
| T-3213 | Tweezer in the workbench UI | DONE — its own surface, not a tab beside the daily engine |
| T-3209 | Not a `Strategy` subclass | OPEN by design — intraday, conditional entry, bracket exit and risk-based sizing cannot be target weights |
| T-3210 | Rebuild the panel with OHLC | OPEN — 2,869 B2 downloads. **The cap is not a blocker** — the operator confirmed B2 is effectively unmetered; just run it |
| T-3214 | Scan a whole universe, not 3 hand-picked symbols | DONE — `--universe nifty50\|nifty100\|nifty250` (ADR-008 liquidity ranking, not index membership) added to `intraday/scan.py`, `make tweezer`, and the workbench `/api/tweezer` route; `scan_many` threads the B2 reads since the work is I/O-bound, not CPU-bound. A symbol with no minute data is reported and skipped rather than failing the whole run. **Widening the universe still has not been run** — T-3212 stays OPEN until it has |

---

## Fleet scale-up — many strategies, many asset classes (2026-08-21)

Operator asked to scale to hundreds of strategies across asset classes, with
RM/TM attachment and a backtest → forward-test → live pipeline. Architecture in
ADR-035 (PROPOSED). Verify: `uv run pytest tests/test_validation_ledger.py`

| ID | Task | Status |
|---|---|---|
| T-3301 | σ_SR is assumed 1.0 and scales the entire noise bar | DONE (instrumented) — `ledger.sharpe_dispersion()` measures it and **refuses** while only 3 entries carry a Sharpe, all H-0001. A-021 |
| T-3302 | Dispersion across distinct subjects, never across entries | DONE — one hypothesis re-evaluated 8 times is one strategy; counting repeats shrinks σ and lowers the bar. Mutation-tested: naive row-counting fails 2 tests |
| T-3303 | Canonical `sharpe` key recorded going forward | DONE — `validation/run.py` writes it alongside the legacy key. Past entries are hash-chained and **must not** be rewritten, so both keys stay readable forever |
| T-3304 | The bar is marked "assumed" wherever it is shown | DONE — `/api/health` returns `noise_bar_sigma_measured`, the workbench marks it. A caveat that travels in the payload, not the page |
| T-3305 | **σ_SR still unmeasured** — needs 5 distinct validated hypotheses | OPEN — the project has 1. Until then the bar rests on an assumption, and at σ_SR ≤ 0.68 the best-ever 1.27 would clear it |
| T-3306 | ADR-035: count trials by family, control FDR not FWER | OPEN — **operator decision.** `mandate.yaml` and `gates.py` untouched. At 1,000 trials the flat counter demands Sharpe 3.26 |
| T-3307 | Effective-N estimator has no primary source | OPEN — A-020. Direction sourced (Harvey/Liu/Zhu §4); the specific method is not |
| T-3308 | `strategies/` package + registry | DONE — `src/eulerlab/strategies/`. Declarations only; it runs nothing. **Stage is derived from the ledger, never stored** — `forward_testing` and `live` are unreachable because no mechanism produces them, and a test asserts no strategy can reach them |
| T-3314 | Fleet console: list, instruments, run pricing | DONE — `/api/fleet`, `/api/capabilities`, `/api/instruments`, `/api/run/price`; `FleetTable`, `InstrumentPicker`, `RunComposer`. Fleet is now the default surface; authoring demoted to one action within it |
| T-3315 | Every Sharpe drawn against the bar, never bare | DONE — sorting by Sharpe stays possible and warns that it is the selection procedure PBO measures. Unmeasured sorts last, never as zero |
| T-3316 | Capability matrix: declared ≠ supported | DONE — `strategies/catalog.py` reads real paths. **Caught a bug in itself**: first version checked `panel.parquet` while the panel is `price_panel.jsonl`, so it reported "not built" for 540 MB on disk. Regression-tested |
| T-3317 | The batch runner behind the composer | OPEN — the cost screen exists first, deliberately. "Run" explains that and does nothing else |
| T-3318 | Result cache, so `cached` is measured not entered | OPEN — the composer's cached count is a what-if control and says so |
| T-3309 | RM/TM as seams between `target_weights()` and order planning | TODO — `Strategy` itself must not change |
| T-3310 | `EventStrategy` for intraday/bracket shapes (Tweezer is not a `Strategy`) | TODO — T-3209 is the same gap |
| T-3311 | Forward-test as an explicit per-strategy stage | TODO — `paper/runner.py` already is the mechanism; the stage is untracked |
| T-3312 | `server.py` has no test coverage | OPEN — no test imports it; the type gate was the only check, and it was red in CI for 5 merges |
| T-3313 | Schedule `make daily` so data actually updates | TODO — exists but nothing runs it; no cron, no launchd |

---

## Integrated from TradeMaster (2026-08-20)

Source: `~/Documents/TradeMaster_Avneesh` (2CentsCapital). Verify: `make montecarlo`.

| ID | Task | Status |
|---|---|---|
| T-3101 | Monte Carlo resampling added to the battery | DONE — ADR-034; the battery had no path-risk test |
| T-3102 | Resample returns, not prices | DONE — holds decisions fixed; costs no backtest |
| T-3103 | Shuffle and bootstrap reported separately | DONE — shuffling cannot move the Sharpe; a test asserts it |
| T-3104 | Unit bug: drawdowns stored as percentages | DONE — printed -2258.9% and inverted the verdict; now stored as fractions |
| T-3105 | Costs no trial | DONE — resampling an existing result evaluates nothing new |
| T-3106 | momentum_12_1 bootstrap 5th percentile is -0.96 | OPEN — over 700 days the data cannot rule out zero edge |
| T-3107 | Kelly position sizing from TradeMaster's risk_management | OPEN — EulerLab is equal-weight only; next candidate to port |
| T-3108 | Walk-forward optimiser (`playground/wfo.py`) | OPEN — CPCV covers most of this; evaluate overlap before porting |
| T-3109 | TradeMaster broker adapters | OPEN — relevant to Sprint 29; patterns only, not code (it wraps backtesting.py) |

---

## The workbench — UI, AI authoring, documentation (COMPLETE 2026-08-20)

Not a numbered sprint in the build plan; requested by the operator. Verify:
`make verify` (7 of 7) · `make workbench` then author a strategy three ways.

| ID | Task | Status |
|---|---|---|
| T-3001 | Sandbox: pasted code runs without discarding the lookahead firewall | DONE — ADR-032; allowlisted AST + attributes + builtins |
| T-3002 | Every classic escape closed and individually tested | DONE — 35 adversarial tests, deny-by-default |
| T-3003 | Unavailable names refused at submit, not as a NameError mid-run | DONE — name resolution in `check()` |
| T-3004 | Provider-agnostic model client; default local and free | DONE — ADR-033; Ollama, no key, no quota |
| T-3005 | Model output validated before it can run | DONE — hallucinated features refused by name |
| T-3006 | FastAPI service reusing the engine unchanged | DONE — optional `web` extra, not a core dependency |
| T-3007 | The API cannot spend a trial or reach the gate | DONE — no ledger-writing route exists |
| T-3008 | Caveats travel in the payload, not the page | DONE — a result without its warnings is the worst artefact here |
| T-3009 | Next.js workbench: describe / compose / code | DONE — `make workbench` |
| T-3010 | `docs/ARCHITECTURE.md` — components and mathematics for a newcomer | DONE — 949 lines, every formula matched to the implementation |
| T-3011 | Sandbox has no CPU limit | OPEN by design — S-021; external timeout is the real protection |
| T-3012 | Ollama not installed on this machine | OPEN — Describe tab reports it; Compose and Code work regardless (S-022) |
| T-3013 | Web UI has no authentication | OPEN — binds to localhost only; revisit before it leaves this machine |

---

## Sprints 19-28 — the order path (COMPLETE 2026-08-20)

Verify: `make verify` (7 of 7) · `make chaos` (11 of 11) ·
`make attribution FRICTIONLESS=1 DAYS=800` (gap must be exactly 0.00)

| ID | Task | Status |
|---|---|---|
| T-1901 | Order state machine as a table, not `if` statements | DONE — ADR-028 |
| T-1902 | `UNKNOWN` is a real state; only a query leaves it | DONE — asserted over the whole table, not over examples |
| T-1903 | `UNSENT` distinct from `REJECTED` | DONE — one the exchange never saw, one it refused |
| T-1904 | A broker can reject synchronously inside the send | DONE — `INTENT -> REJECTED`; **found by a failing test, the table was missing it** |
| T-2001 | Write-ahead journal: intent fsynced before the network call | DONE — ADR-029 |
| T-2002 | Torn final line dropped, mid-file corruption raises | DONE — a damaged journal must never read as an empty one |
| T-2003 | Sequence numbers detect a deleted event | DONE — chose this over a hash chain; see the module docstring |
| T-2004 | Idempotent submit on the deterministic client order id | DONE — two-deep: our records, then the broker's duplicate rejection |
| T-2005 | Recovery makes every non-terminal order `UNKNOWN`, then asks | DONE — including `ACKNOWLEDGED`, which is a stale cache after a crash |
| T-2006 | A broker denying an order we have fills for is a BREAK, not a resolution | DONE — refuses both readings, escalates to a human |
| T-2101 | Rate governor: a sliding window, not a token bucket | DONE — a bucket permits 10 inside 200ms across a boundary |
| T-2102 | `max_orders_per_second` read from config, not a literal | DONE — a test asserts it comes from `config/execution.yaml` |
| T-2103 | Injected clock so the limit is testable without sleeping | DONE — 37 sends checked against every one-second window |
| T-2201 | Reconciler: four break kinds, worst first | DONE — `broker_only` is the dangerous one |
| T-2202 | Reconciliation places no orders, ever | DONE — ADR-030; there is no flag to enable it |
| T-2203 | Local positions derived from the journal, not from memory | DONE — the comparison must be against post-restart state |
| T-2301 | Kill switch: anything may trip, almost nothing may clear | DONE |
| T-2302 | No importable reset function; clearing needs `KILLSWITCH_TOKEN` | DONE — test asserts no other module in `src/` names the variable |
| T-2303 | Automatic limits: loss, order count, rejections, position, unresolved | DONE — `config/killswitch.yaml` |
| T-2304 | The first trip reason survives later trips | DONE — later ones are consequences of having stopped |
| T-2305 | An unreadable trip file still reads as tripped | DONE — failing to parse must never mean "clear" |
| T-2401 | `BrokerAdapter` protocol; three send outcomes, three exception types | DONE — `BrokerUnreachable` is the honest default |
| T-2402 | `PaperBroker` with its own durable state file | DONE — a dict inside the OMS would make every reconciliation test circular |
| T-2403 | Fault injection: recorded-then-raised vs raised-without-recording | DONE — identical at the call site, opposite truths |
| T-2404 | Chaos suite, two scenarios `SIGKILL` a real subprocess | DONE — `make chaos`, 11 of 11, and in `make verify` |
| T-2501 | `plan_orders` extracted so backtest and paper share one implementation | DONE — golden file unchanged, so the refactor moved no behaviour |
| T-2502 | Fill step is a pluggable `Executor` | DONE — ADR-031; paper is the same loop with one component swapped |
| T-2503 | A frictionless paper run reproduces the backtest **exactly** | DONE — `gap == 0.00`, asserted as equality not tolerance |
| T-2504 | An ambiguous send is resolved mid-run, not at next start-up | DONE — **found by a failing test**; a timeout now costs nothing |
| T-2601 | Reality-gap decomposition into five named causes | DONE — `make attribution` |
| T-2602 | The decomposition closes to the paisa | DONE — checked against 0.01 rupees, not 10% |
| T-2603 | State plainly that the residual is an identity, not a measurement | DONE — S-018; both books are ours |
| T-2604 | Live reality-gap residual under 10% | **NOT DONE — impossible before Sprint 29.** Needs a real counterparty. The machinery exists and is verified against a case where the true answer is known |
| T-2605 | Live Kite order adapter | OPEN — deliberately deferred; decision question 2 in the review |
| T-2606 | `ACKNOWLEDGED` / `PARTIALLY_FILLED` exercised by a real venue | OPEN — modelled and unit-tested, never produced by the paper broker (S-016) |
| T-2607 | Kill-switch limits set from an observed distribution | OPEN — A-018; needs ~4 weeks of paper history |
| T-2608 | Decide whether `config/killswitch.yaml` becomes operator-owned | OPEN — operator decision, question 1 in the review |
| T-2609 | **A trial was spent by accident during end-to-end testing** | RECORDED — running `make gate H=H-0001` to check the command still works logged ledger entry #19, a second evaluation of an already-killed hypothesis. The count went 18 -> 19 and the noise bar went Sharpe 1.83 -> 1.88, for every future candidate. There is no un-spend function and there should not be. `make acceptance` therefore excludes every command that writes to the ledger, and says so in its docstring |
| T-2610 | `make acceptance` — every sprint's capability on the real data | DONE — distinct from `make verify`, which only proves the repository is healthy |

---

## Sprints 16-18 — the research agent loop (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1601 | Codegen composes vetted primitives, never writes Python | DONE — ADR-027; `exec` would discard Sprint 4's firewall |
| T-1602 | An unknown primitive raises rather than being skipped | DONE — else a card is judged on a different set than it registered |
| T-1603 | Critic reviews before a trial is spent, reading no price data | DONE — outcome-peeking is how a trial gets laundered |
| T-1604 | Critic is advisory and cannot kill | DONE — heuristics must not hold a veto |
| T-1605 | Orchestrator weekly report: tested, passed, killed, and **why** | DONE — `make research` |
| T-1606 | Gate verdicts read from the ledger, not tracked separately | DONE — the report cannot drift from the evidence |
| T-1607 | New strategy shapes need hand-written primitives | OPEN by design — the brake is intentional |
| T-1608 | Critic raised no blocker on H-0001, which the gate killed | OPEN — one data point, wrong direction; revisit after more reach the gate |
| T-1609 | Run the loop end to end on a registered hypothesis | OPEN — needs T-1317 first; the critic objects to H-0002 |

## Sprint 15 — paper scout and hypothesis cards (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1501 | `make scout` prices a search before running it | DONE — ADR-026; 20 more hypotheses moves the bar 1.83 -> 2.16 |
| T-1502 | Hypothesis cards as specs with mandatory red flags | DONE — hedges rejected by the validator |
| T-1503 | Cards refuse to overwrite; ids never recycled | DONE — a pre-registration is not rewritten |
| T-1504 | A card without a real source is refused | DONE — CLAUDE.md forbids inventing one |
| T-1505 | H-0002 drafted from real NSE literature | DONE — research note 014; **draft, not registered** |
| T-1506 | Decide how many hypotheses the loop should generate | OPEN — operator; 20 makes the bar 2.16 vs our best 1.27 |
| T-1507 | Register H-0002, or wait for T-1317 | OPEN — operator; its own red flags argue for waiting |

## Sprint 14 — promotion gate (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1401 | `mandate.yaml` — operator-owned thresholds, no logic | DONE — **hands off from here** |
| T-1402 | `gates.py` — logic only, no thresholds | DONE — ADR-025; a test asserts no literal thresholds |
| T-1403 | Acceptance: 3 overfit strategies, all killed | DONE — noise, regime, lookahead; all KILLED |
| T-1404 | The regime stress can be slipped past | OPEN — `RegimeFit` retained 76%; split is at the midpoint only |
| T-1405 | Holdout: one read, refused on KILL and when spent | DONE — no un-spend function exists |
| T-1406 | Gate decisions written to the trial ledger | DONE — a resubmission under a new id is visible |
| T-1407 | Exercise the PROMOTE path with a known-good synthetic candidate | OPEN — the gate has never promoted anything |
| T-1408 | Formally mark H-0001 killed | OPEN — operator decision; the gate has said KILL |

## Sprint 13 — overfitting battery (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1301 | CPCV with purge + embargo | DONE — 15 paths, leakage asserted per path |
| T-1302 | Deflated Sharpe, MinBTL, expected-max-Sharpe | DONE — all take the trial count as required |
| T-1303 | PBO | DONE — **53.3%, worse than a coin flip** |
| T-1304 | Tamper-evident trial ledger | DONE — ADR-023; battery refuses to report on a broken chain |
| T-1305 | Holdout reserved and structurally unreachable | DONE — 2025+ never read |
| T-1306 | `hypotheses/H-0001.yaml` with red flags declared in advance | DONE |
| T-1307 | `make validate` + hash-signed evidence pack | DONE — JSON not PDF |
| T-1308 | Fix the leakage check (condemned 14 of 15 correct paths) | DONE — measured the filtered timeline, not the real one |
| T-1309 | 14x engine speedup via strategy-declared lookback | DONE — 95s to 6.9s, byte-identical output |
| T-1310 | Investigate excess kurtosis of +101 and +161 | DONE — led to the raw-price marking bug below |
| T-1313 | Panel stores raw prices + instrument key; guard against silent no-op | DONE — panel rebuilt, 2,869 days |
| T-1314 | Point-in-time adjustment for signals, consistent series for marking | DONE — phantom P&L removed |
| T-1315 | Re-run the Sprint 13 battery on corrected prices | DONE — PBO 53.3% -> **60.0%**; verdict unchanged |
| T-1316 | Re-run Sprint 10/11 backtests on corrected prices | DONE — momentum +16.8% ann. vs buy-and-hold +4.6% |
| T-1317 | Re-run the Sprint 8 IC sweep on corrected prices | OPEN — IC figures still come from raw prices |
| T-1318 | Hoist the adjusted-price index out of `run()` | DONE — but only 1.6s of 16s; the loop dominates |
| T-1319 | Parallelise the CPCV sweep | OPEN — 150 independent backtests, ~40min serial |
| T-1311 | Stress tests | DONE — costs, staleness, concentration, regime. **Regime split: Sharpe 0.49 vs 1.48** |
| T-1312 | Decide H-0001's fate (CLAUDE.md: a failed strategy is dead) | OPEN — operator decision |

## Sprint 12 — backtester self-tests (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1201 | Accounting invariants checked per event | DONE |
| T-1202 | Zero alpha = exact cost drag | DONE — loses Rs 78,113.65, matching fees to the paisa |
| T-1203 | Known-alpha recovery | DONE — recovers 67.4% of a planted 67.8% |
| T-1204 | Determinism, both engines | DONE |
| T-1205 | Golden file on a synthetic world | DONE — stable as real data grows |
| T-1206 | Mutation suite: prove every check can fail | DONE — **found a hole in the gate** |
| T-1207 | Independent cost recomputation | DONE — added because doubling fees passed the cost-drag check |
| T-1208 | `make verify` runs the engine gate | DONE — now 6 of 6 |
| T-1209 | Fix Sprint 8's null anchor | DONE — was non-deterministic *and* not a true null (t=4.7) |
| T-1210 | Property-based testing (Hypothesis) | OPEN — the assigned reading; example-based tests only find imagined bugs |

## Sprint 11 — Tier B event-driven backtester (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1101 | Order/Fill/Rejection/Portfolio vocabulary | DONE — `backtest/events.py` |
| T-1102 | Event-driven engine, same `Strategy` unadapted | DONE — `backtest/event_driven.py` |
| T-1103 | Deterministic client order ids + `algo_id` from day one | DONE — retry cannot double-send |
| T-1104 | Reconciliation against Tier A | DONE — **8.05e-16 relative over 1,587 days** |
| T-1105 | `make backtest` | DONE — runs both and reconciles every time |
| T-1106 | Extend panel to 2015 | DONE — 1,841 days; **overturned Sprint 10's conclusion** |
| T-1107 | Re-run the Sprint 8 IC sweep on the 11-year panel | OPEN — all Sprint 8 conclusions used the 3-year window |
| T-1108 | Limit/stop orders, partial fills | OPEN — lifecycle supports them; nothing needs them yet |

## Sprint 10 — Tier A vectorised backtester (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1001 | One `Strategy` interface, engine never learns a strategy name | DONE — ADR-021 |
| T-1002 | Vectorised engine, next-bar fills, one cost path | DONE — `backtest/vector.py` |
| T-1003 | `cost_mode` realistic/replication | DONE — borrowed from the reference system |
| T-1004 | Buy-and-hold control | DONE — +10.1% ann., -20.0% DD; the engine's sanity anchor |
| T-1005 | `make backtest-fast` | DONE — ~25s |
| T-1006 | Fix silent zero-valuation of non-trading holdings | DONE — had manufactured a -50% drawdown |
| T-1007 | Liquidity screen on rank strategies | DONE — default off so the naive result stays visible |
| T-1008 | Market impact model | OPEN — deferred to Tier B where fills are explicit |
| T-1009 | Extend panel to 2015 before interpreting drawdowns | OPEN — now blocking interpretation (T-807) |

## Sprint 9 — cost model (PARTIAL 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-901 | Research Indian transaction costs from sources | DONE — research note 013, every rate sourced and dated |
| T-902 | Time-versioned rate schedule | DONE — ADR-020; futures STT 4x across the window |
| T-903 | Itemised per-leg cost model | DONE — sides modelled, GST on fees not turnover |
| T-904 | Resolve A-005 (STT on exercise) | DONE — **the playbook was wrong since 2019**; both rules implemented |
| T-905 | `make check-costs` acceptance gate | DONE — 4 green, 1 PARTIAL pending contract notes |
| T-906 | **Reconcile against 20 real contract notes** | BLOCKED — needs the operator; `config/contract_notes.example.json` is ready |
| T-907 | Slippage and square-root impact | OPEN — deferred to meet the backtester |
| T-908 | Verify pre-2024 F&O rates were contemporaneous | OPEN — A-016 |
| T-909 | Verify the rest of A-005 (cash settlement, physical delivery) | OPEN |

## Sprint 8 — feature library and IC harness (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-801 | Adjusted price panel, cached and resumable | DONE — 892 days, 3,331 symbols, 2.0M rows; joins on InstrumentId |
| T-802 | Ten seed features, pure functions of their own history | DONE — signs normalised so higher is always better |
| T-803 | Rank-IC harness through the lookahead firewall | DONE — ADR-019 |
| T-804 | Harness calibrated at both ends | DONE — oracle feature scores exactly 1.0, noise ~0 |
| T-805 | Tear sheet with t-stat, hit rate, per-year breakdown | DONE — `make ic`, 75s |
| T-806 | Append-only trial counter | DONE — started now, not in Sprint 13, per ADR-019 |
| T-807 | Extend the panel to 2015 | OPEN — ~1,980 B2 downloads; 2023-2026 is almost all bull market |
| T-808 | Factor neutralisation (size, liquidity) | OPEN — the assigned reading covers it; harness does not do it yet |
| T-809 | Fundamental features | OPEN — screener.in data has no per-field knowledge_time |
| T-810 | Apply the overlap correction to the t-statistic | OPEN — described in the tear sheet, not applied; part of Sprint 13 |
| T-811 | Independence clustering of the IC sweep | DONE — 10 features are ~3 findings; printed automatically |

## Sprint 7 — options quality (PARTIAL 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-701 | Option chain model from F&O bhavcopy, both eras | DONE — reuses Sprint 3 contract identity |
| T-702 | Put-call parity against the same-expiry future | DONE — forward implied from the chain, no rate assumed |
| T-703 | Strike monotonicity, butterfly convexity, intrinsic bounds | DONE — hard inequalities, not thresholds |
| T-704 | Calendar inversion check | DONE — WARN only; European futures options do not guarantee the textbook inequality |
| T-705 | Own IV via Black-76, bisection | DONE — 25 tests, round-trip at every moneyness |
| T-706 | Theil-Sen fit so one bad quote cannot hide itself | DONE — ADR-018; OLS was silently returning no findings |
| T-707 | `make quality-options` | DONE — cap path verified end to end |
| T-708 | Run against real F&O chains | DONE — 2 days NIFTY; **forward fit validated to 2.5pts of the actual future on 24,400 (0.01%)**; 56 lower-bound ERRORs on deep-ITM stale marks |
| T-709 | Calibrate the options tolerances | DONE — note 012. Absolute Rs 1.00 flagged 45.95% of pairs; now 2% of forward. Findings 3,161 → 782 |
| T-710 | Diagnose the DAYS=5 segfault | DONE — not reproducible in 3 runs; memory ruled out (106 MB/day). S-014 kept open honestly |
| T-711 | Build a labelled set of known-bad rows so thresholds can be optimised, not just calibrated | OPEN — note 012 |

## Sprint 6 — data quality engine (PARTIAL 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-601 | MAD-based robust statistics | DONE — ADR-017, note 011, measured not asserted |
| T-602 | Manifest checks: coverage, gaps, staleness, duplicates | DONE — zero B2 cost, runs under the cap |
| T-603 | Row checks: OHLC invariants, turnover, extreme moves, spikes, stale runs | DONE (code+tests) — not yet run on real prices |
| T-604 | Cross-source reconciliation: bhavcopy vs Kite minute bars | DONE (code+tests) — not yet run on real data |
| T-605 | Suppression by STUBS id, never by threshold | DONE — pinned per date/symbol so a new defect still reports |
| T-606 | `make quality` report with counts by severity | DONE — 0 errors on the free checks |
| T-607 | Run `make quality ROWS=...` against real prices | DONE — 634,453 symbol-days; noise cut 6,892 → 740 findings |
| T-608 | Run the cross-source reconciliation against real data | DONE — `make reconcile`; **2 disagreements in 240 symbol-days**, median vendor difference 0.181% |
| T-609 | Calibrate the spike threshold | DONE — measured on 632,133 symbol-days: old 5.0 was the *99th percentile* of ordinary trading (1.04% flagged). Now 15.0 = p99.9 |
| T-611 | Add ETF/fund corporate actions | OPEN — S-013, found by the quality engine |

## Sprint 5 — corporate actions and adjustment engine (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-501 | Ingest the NSE corporate-actions feed, 2015-2026 | DONE — 12 years, 25,713 actions, real B2-synced |
| T-502 | Parse free-text `subject` into typed dividend/bonus/split/rights | DONE — 94.3% parse rate on real data, `parse.py` |
| T-503 | Price-adjustment factor engine (bonus + split) | DONE — run against full real dataset, `adjust.py` |
| T-504 | Total-return factor engine (+ dividends reinvested) | DONE, unit-tested — S-010: full historical run not executed this session |
| T-505 | Wire the adjustment engine through Sprint 4's bitemporal firewall | DONE — `factor_as_of` requires `as_of`, ADR-016 |
| T-506 | Rights-issue price effect | DONE — `P/TERP`, research note 010, A-015, 11 tests |
| T-507 | Source real corporate-action announcement dates (tighten knowledge_time past ex-date) | OPEN — ADR-016 |
| T-508 | `make build-factors` — cached, resumable full factor build | DONE — one full run completed in 3m30s |
| T-509 | Join corporate actions to bhavcopy on `InstrumentId`, not raw ISIN | DONE — was losing 21.9% of price lookups; regression-tested |
| T-510 | Re-run `make build-factors` after the ISIN-join fix | DONE — coverage 78.1% → **98.1%**, +3,073 dividend factors |
| T-511 | Read the NSE circular itself for the rights formula (currently a broker's summary) | OPEN — A-015 |
| T-512 | `make check-adjust` — the build plan's stated Sprint 5 acceptance gate | DONE — 6 checks green, 1 skipped pending S-012 |

## Sprint 4 — lookahead firewall (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-401 | Bitemporal read API, `as_of` required and keyword-only | DONE — ADR-014 |
| T-402 | Adversarial test suite against the firewall | DONE — 36 tests, `make test-lookahead` |
| T-403 | Wire the store to real landing-zone manifests | DONE — found the download-time defect |
| T-404 | Separate knowledge time from receipt time | DONE — ADR-015, `make provenance` |
| T-405 | Point-in-time universe guard (survivorship) | DONE — `bitemporal/universe.py` |
| T-406 | Source the real NSE publication hour per segment | OPEN — A-014, before Sprint 9 or any intraday work |
| T-407 | Persist the store to Parquet when a dataset exceeds memory | OPEN — no measured need yet |

## Sprint 0 — Scaffolding · **COMPLETE**

Verify: `make verify`

| ID | Task | Status |
|---|---|---|
| T-001 | `pyproject.toml` + uv lockfile, ruff, mypy strict, pytest, pre-commit | DONE |
| T-002 | `Makefile`: `verify` `test` `lint` `fmt` `types` `docs-check` `state` | DONE |
| T-003 | `tools/verify.py` — prints the green/red table, non-zero exit on failure | DONE |
| T-004 | `tools/docs_check.py` — src/ change without docs fails | DONE |
| T-005 | `tools/state.py` — STATE.md is machine-readable | DONE |
| T-006 | `STATE.md`, `TASKS.md` seeded through sprint 14 | DONE |
| T-007 | `docs/` tree, every type present with a worked example | DONE |
| T-008 | `.github/workflows/ci.yml` — lint, types, tests, docs-check | DONE |
| T-009 | `docs/READING/index.md` — MUST list for sprints 1–4 | DONE |
| T-010 | Compliance stubs: `algo_id`, `max_orders_per_second`, `static_ip` | DONE |
| T-011 | `docs/SPRINT_00_REVIEW.md` | DONE |
| T-012 | `.gitignore` covers `data/`, `.env`, `__pycache__`, `.venv` | DONE |

**Acceptance criteria** (from the kickoff doc):

- [x] `make verify` runs and prints a green table
- [x] **CI passes on a pushed branch** — run 32088448395, all five gates green in 13s
- [x] A `src/` change with no doc change makes `docs-check` fail — tested
      deliberately, and permanently in `tests/test_docs_check.py`
- [x] `STATE.md` describes reality in under one page
- [x] `docs/READING/index.md` has the MUST list for sprints 1–4
- [x] `.gitignore` covers `data/`, `.env`, `__pycache__`, `.venv`

---

## Sprint 1 — NSE EOD ingest · **IN PROGRESS** (backfill running)

Verify: `make ingest-eod FROM=2015-01-01`, then run it again — second run must
download nothing.

**Decided 2026-08-18:** history starts at **2015-01-01** (~11 years). Cheap to
extend later — the downloader is idempotent, so widening the range re-fetches
only the new days.

| ID | Task | Status |
|---|---|---|
| T-101 | Research NSE archive URLs + schemas → `docs/RESEARCH/002-nse-eod-sources-and-schemas.md` | DONE |
| T-109 | Source the trading calendar (holiday vs failed download) — cannot be derived from file absence | TODO — blocks T-107 |
| T-110 | Handle both bhavcopy formats: legacy (2015→mid-2024) and UDiFF (2024-01→), probing rather than hardcoding the cutover | DONE |
| T-111 | Cross-validate the two schemas on the Jan–Jul 2024 overlap window where both formats exist | TODO |
| T-112 | Review NSE's terms on automated archive access before the first full backfill (A-010) | DONE — **terms prohibit it.** Backfill not run |
| T-113 | Decide a history source given NSE's terms | DONE — operator chose to proceed from the public archive anyway (ADR-006) |
| T-115 | Run the full 2015→2026 backfill | IN PROGRESS — ~5,800 requests, ~6–7 hours, resumable |
| T-116 | `make sync-cloud` — mirror the landing zone to Backblaze B2 (ADR-007) | DONE (code) — **unwired**, needs bucket + key |
| T-117 | Create the B2 bucket and an application key, fill `config/storage.yaml` and `.env` | TODO — operator action, blocks T-118 |
| T-118 | Run the first full cloud sync and verify every checksum | BLOCKED — needs T-117 |
| T-102 | Bhavcopy + F&O bhavcopy downloader into `data/landing/`, gzipped, one file per day | DONE |
| T-103 | Idempotency: re-run downloads zero files and says so | DONE — proven on real data, 20.6s then 1.3s |
| T-104 | Resumability: Ctrl-C mid-run, restart, resumes correctly | DONE — proven against SIGKILL, stronger than Ctrl-C |
| T-105 | Rate limiting + retry with backoff | DONE |
| T-106 | Summary output: date range, fetched, skipped, rows parsed, holidays | DONE |
| T-107 | Missing-day report distinguishing "market holiday" from "download failed" | DONE — three honest states, never guesses |
| T-108 | Landing zone is immutable — files never modified after write, enforced by test | DONE — `make check-landing` |

---

## Sprint 2 — Options chain recorder · **DEFERRED** (2026-08-18, operator decision)

**Deferred in favour of finishing the equities stack first.** The reasoning
against deferring is on the record and unchanged: NSE sells no cheap historical
option-chain data, so every day the recorder is not running is a day that cannot
be bought back at any price. Measured cost of doing it: full chains at 5s is
~300-550 MB/day; **near-expiry-only is ~35-65 MB/day**, roughly a tenth, and
still captures the irreplaceable part. Worth revisiting as a background job.

The blocking research is already done and does not expire — see
`docs/RESEARCH/003-kite-feasibility-for-the-options-recorder.md`: the recorder
must be WebSocket-based, because polling the full chains takes 9 seconds against
a 5-second target.

Verify: `make recorder-status`

| ID | Task | Status |
|---|---|---|
| T-201 | **Decide the live data source** | DONE — Zerodha Kite Connect only, ₹500/mo (ADR-004) |
| T-211 | **Verify Kite permits a 5s full-chain snapshot** against its documented rate limits — A-008 | TODO — **first task of Sprint 2, before any recorder code** |
| T-212 | Confirm Kite Connect account + API key issued | TODO — operator action, has lead time |
| T-202 | Provision a Mumbai-region VPS (~₹500–900/mo) | TODO — operator action. Decided 2026-08-18: VPS, not the laptop. A laptop that sleeps or drops wifi puts unrepairable holes in the history |
| T-203 | Snapshot Nifty (NSE) + Sensex (BSE) chains every 5s, 09:15–15:30 IST, trading days | TODO |
| T-204 | Parquet, partitioned by date, **both** exchange timestamp and receive timestamp per row | TODO |
| T-205 | systemd unit, auto-restart on crash | TODO |
| T-206 | Survives a network drop and resumes without gaps | TODO |
| T-207 | Disk usage projected and logged (estimate 50–200 MB/day; confirm with real numbers) | TODO |
| T-208 | `make recorder-status`: last snapshot, rows today, gaps today, disk free | TODO |
| T-209 | Daily Telegram heartbeat so a death is noticed within a day | TODO |
| T-210 | `docs/RUNBOOKS/recorder.md` | TODO |

---

## The equities path — next up

With options deferred, sprints 3-6 need **nothing from the operator**: no VPS,
no new spending, all local computation over data already landed.

| # | Build | Verify by | Status |
|---|---|---|---|
| 3 | Security master: instruments, time-versioned lot sizes, calendars | `make check-master` | **NEXT** |
| 4 | Bitemporal read API + lookahead firewall | `make test-lookahead` | TODO |
| 5 | Corporate actions + adjustment engine | `make check-adjust` | TODO |
| 6 | Data quality engine | `make quality` | TODO |

Sprint 7 (options quality) moves to wherever the recorder lands.

## Sprint 3 — security master · **COMPLETE**

Verify: `make verify` and `make check-master` (6 of 6)

| ID | Task | Status |
|---|---|---|
| T-301 | Internal instrument id, measured not assumed (ADR-012) | DONE |
| T-302 | Time-versioned registry, `at(as_of)` returns what was true then | DONE |
| T-303 | Build from bhavcopy, streaming from B2 | DONE |
| T-304 | Symbol-change map from ISIN continuity — 580 renames | DONE |
| T-305 | Succession model: rename / merger / demerger / cancellation (ADR-013) | DONE |
| T-306 | Fix the BE-series lookup bug (4 false delistings) | DONE |
| T-307 | Refetch minute bars for 24 recovered symbols | DONE — 420 symbols, 184M bars |
| T-308 | F&O composite key (symbol, expiry, strike, right) | DONE — 28,984 contracts in 2015 and 35,089 in 2026 parsed, zero failures, zero duplicate keys |
| T-309 | Trading calendar from evidence, not weekday rules | DONE — 2,869 trading days; flags 2021-03-30 SUSPECT rather than guessing |
| T-310 | `make check-master` | DONE — 6 checks, all green, each capable of failing |
| T-311 | Verify lot-size history against a known past value (A-002) | DONE — NIFTY 50/25/75/65 read from our own bhavcopy; A-002 resolved |
| T-312 | Resolve TATACOFFEE ratio | DONE — one scheme, two legs: 1/22 + 14/55 = 3/10 exactly. Sources never disagreed |
| T-313 | Research DHANI, JPASSOCIAT successions | DONE — DHANI→IBULLSLTD (terms_pending), JPASSOCIAT delisted in insolvency |

## Sprints 4–14 — seeded scope

| # | Build | Verify by | Status |
|---|---|---|---|
| 3 | Security master: instruments, time-versioned lot sizes, broker symbology, calendars | `make check-master` → zero unmapped symbols; lot size as of any past date | TODO |
| 4 | Bitemporal read API + lookahead firewall + adversarial test suite | `make test-lookahead` → ~15 attack tests, all blocked | TODO |
| 5 | Corporate actions + adjustment engine | `make check-adjust` reproduces a known adjusted series exactly | TODO |
| 6 | Data quality engine: gaps, OHLC sanity, MAD spikes, staleness, cross-source recon | `make quality` → counts by severity | TODO |
| 7 | Options quality: put-call parity, strike monotonicity, butterfly convexity, own IV | `make quality-options` | TODO |
| 8 | Feature library + IC harness, 10 seed features | `make ic FEATURE=momentum_12_1` → tear sheet <2 min | TODO |
| 9 | Cost model: brokerage, STT (incl. exercise), stamp duty, GST, fees, slippage, impact | `make check-costs` reproduces 20 real contract notes to the paisa | TODO |
| 10 | Tier A vectorised backtester (screening only) | `make backtest-fast STRAT=demo` | TODO |
| 11 | Tier B event-driven backtester, same `Strategy` interface as live | `make backtest` | TODO |
| 12 | **Backtester self-tests** — invariants, known-alpha recovery, zero-alpha = exact cost drag, determinism, golden files | `make test-engine` — *the most important gate in the project* | TODO |
| 13 | Overfitting battery: CPCV purge+embargo, DSR, PBO, MinBTL, tamper-evident trial counter | `make validate H=H-0001` → signed evidence pack | TODO |
| 14 | Promotion gate as code + pre-registration; locked holdout, single enforced read | Feed it 3 deliberately overfit strategies; all must be killed | TODO |

**Scope only, not yet planned:** 15–18 research agent loop · 19–24 OMS/EMS,
kill switches, first broker adapter · 25–28 paper trading + reality-gap
attribution · 29–30 compliance sprint · 31 first micro-live capital (1–2%).

---

## Discovered during Sprint 0

| ID | Item | Status |
|---|---|---|
| T-013 | Push to a private GitHub repo so CI actually runs | DONE — `Avneeshwork/eulerlab`, private |
| T-017 | Bump `actions/checkout` v4→v7 and `astral-sh/setup-uv` v5→v10 (Node 20 deprecation warning on first run) | DONE |
| T-014 | Verify the ~10 OPS SEBI threshold against the primary circular (A-001) | TODO — Sprint 29, or sooner if convenient |
| T-018 | Add Dhan as a second free feed for cross-reconciliation | DEFERRED — revisit when the quality engine (Sprint 6–7) flags anomalies a single source cannot adjudicate (ADR-004) |
| T-015 | Verify current Nifty/Sensex lot sizes and expiry days against NSE/BSE circulars (A-002, A-003) | TODO — blocking for Sprint 3 |
| T-016 | `mandate.yaml` + `gates.py` — operator-owned, written **with** the operator | TODO — Sprint 14 |

| T-314 | Persist the master with a build stamp | DONE — JSONL, deterministic, `make build-master` |
| T-315 | Broker symbology map (internal id ↔ Kite token) | DONE — 71.9% of mappable equities; residual is SME listings absent from the main board |
| T-316 | Ingest SME-platform listings so the broker map reaches 100% | **SKIPPED** — operator decision 2026-08-19. SME names are illiquid and outside the tradable universe; 71.9% coverage of main-board equities is the intended scope, not a shortfall |
| T-317 | Run `make build-master --cadence daily` once, to catch renames that reverse inside a month | TODO |
