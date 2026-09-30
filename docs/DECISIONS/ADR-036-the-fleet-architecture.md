# ADR-036 — The fleet: many strategies, many asset classes, many brokers

**Date:** 2026-08-21 · **Sprint:** fleet scale-up · **Status:** **PROPOSED**

Scaling from one strategy to hundreds. Informed by two of the operator's prior
systems: `~/Documents/Trade` (RM/TM registries, live engine, dashboard) and
`~/TradeMaster_Avneesh` (Backtest→Forwardtest→LiveBroker chain, broker
aggregator). Both were read in full; what each got right and wrong is cited
where it shaped a decision.

---

## The constraint everyone gets wrong

Scaling a research platform looks like a compute problem. **Here it is an
accounting problem.** Running a thousand strategies is not merely expensive in
CPU — it is expensive *permanently*, because every configuration evaluated
raises the bar for every future candidate, forever. Our own function puts the
bar at Sharpe **3.26** after 1,000 trials; the best result this project has ever
produced is **1.27**.

So the first architectural requirement is not parallelism. It is that searching
remains **accountable** while its volume goes up by two orders of magnitude.
ADR-035 (family-based counting, FDR control) is therefore a prerequisite for
this ADR, not a companion to it. Build the parallel runner first and you get a
fleet that can generate a thousand results and justify none of them.

---

## Decision 1 — Two strategy shapes, one downstream

Today's `Strategy.target_weights(view) -> {symbol: weight}` is correct and must
not be widened. It cannot express Tweezer (conditional entry, bracket exit,
risk-based sizing — recorded as T-3209) or an options spread.

**The failure mode is documented in our own source.** `backtest/strategy.py`
already notes that `~/Documents/Trade`'s `run_backtest()` reached 636 lines and
branches on strategy *class names*. That is what happens when one interface is
stretched to cover shapes it cannot express: the engine learns which strategy it
is running, and there is no interface left.

So: **a second interface, not a wider first one.**

| | `PortfolioStrategy` | `EventStrategy` |
|---|---|---|
| Emits | target weights | `Intent` objects |
| Suits | cross-sectional, factor, long-term | intraday, bracket, pattern, options |
| Decides on | rebalance dates | every bar |
| Exists today | yes, unchanged | no — Tweezer is bolted alongside |

Both compile to the same `Intent` stream downstream, so RM, TM, the allocator,
the OMS and the reality-gap attribution each have exactly one input type. A
weight is simply an intent that says "hold this fraction".

---

## Decision 2 — RM and TM are seams, and they are inside the firewall

```
Strategy → Intents → RM.size() → TM.manage() → Allocator → OMS/EMS → Broker
            what        how          when          net       send     route
```

- **RM (risk manager)** turns an intent into a quantity: equal-weight (today's
  behaviour, the default), volatility-target, fixed-fractional, Kelly (T-3107).
- **TM (trade manager)** turns an open position into exit conditions: stop,
  target, trailing, time-stop, breakeven. Tweezer's bracket executor is already
  a TM; it is generalised rather than duplicated.

Both are attached per strategy, from config, and both are **pure functions of a
`MarketView`**. That last point is the one both reference systems miss. In
`~/Documents/Trade`, RM/TM are duck-typed modules discovered by `pkgutil` and
injected as attributes onto a strategy class at live-engine time; nothing stops
one reading a price it should not see. A sizer that peeks at tomorrow's
volatility is lookahead exactly as much as a signal that does, and it will not
show up in any signal-level test. **RM and TM inherit the firewall or they are a
back door into it.**

TradeMaster's `base_rm.py` / `base_tm.py` are explicitly *not* the template:
they are stubs never wired into `Strategy` or `Backtest`, with no tests.

---

## Decision 3 — The allocator, which neither reference system has

With N strategies running at once, something must sit between their intentions
and the market:

1. **Netting.** Strategy A wants +100 RELIANCE, strategy B wants −60. Sending
   both pays two spreads and two sets of charges to achieve +40.
2. **Capital allocation.** Each strategy gets a slice; slices must sum to
   something the account can support.
3. **Portfolio-level limits.** Gross and net exposure, per-instrument
   concentration and per-asset-class caps apply to the *book*, not to each
   strategy in isolation. Five strategies each within their own limit can be
   collectively over.
4. **One kill switch for all of it.**

Neither `~/Documents/Trade` nor TradeMaster has this layer, because both run one
strategy at a time. It is the single largest genuinely new component here, and
skipping it means paying double costs and breaching limits invisibly.

---

## Decision 4 — Stage is data, not which command you ran

`registered → backtested → forward_testing → live → retired`

Today the stage is implicit in which `make` target was last run. At fleet scale
that is unusable: a hundred strategies each sit at their own stage
simultaneously, and "is this live?" must be answerable without reading shell
history.

Stage lives with the strategy, and transitions carry requirements — minimum time
in forward test, a reality gap inside tolerance, a passing gate. `paper/runner.py`
is already the forward-test *mechanism* (the Tier B engine with `OMSExecutor`
swapped in); what is missing is the *record*. TradeMaster has a `Forwardtest`
class and `~/Documents/Trade` has no forward-test stage at all — the second is
the more dangerous omission, since it puts backtest straight into live.

---

## Decision 5 — Cache results, and never let the cache launder a trial

A content-addressed cache keyed on
`hash(strategy_id, params, data_version, cost_model_version)` is what makes a
thousand backtests affordable. It also creates a way to cheat, so the rule is
explicit:

- A **cache hit is not a trial.** Re-running an unchanged strategy against
  unchanged data evaluates nothing new.
- A **cache miss is always a trial.** New configuration, new data version, or a
  changed cost model each mean a genuinely new evaluation.

Get this backwards in either direction and the ledger stops meaning anything:
count re-runs and the bar rises for no search; skip new configurations and the
search is laundered. Pinning `data_version` into the key is also what makes a
fleet result reproducible after the next ingest.

---

## Decision 6 — Multi-broker is routing; multi-user is restraint

**Brokers.** A `BrokerRouter` maps `(asset_class, account) → adapter`. The
existing `BrokerAdapter` protocol and its three send outcomes stay as they are —
they were designed for this. Two things become per-broker rather than global:
the rate governor (each venue has its own limit) and credentials.
TradeMaster's `BrokerAggregator` is the right shape and is worth borrowing;
its hardcoded credentials are not.

**Users.** The operator chose *architecture-ready, not built*. So: no singletons
keyed to one operator, paths derived from a workspace root that defaults to
today's layout, credentials per account rather than per process. No auth, no
tenancy, no per-user billing until there is a second user — consistent with
`CLAUDE.md`'s cost discipline and its "single operator" premise, which this
does not yet reverse.

One question is deferred deliberately because it is a research decision rather
than an engineering one: **whether two users share a trial ledger.** Sharing is
statistically correct when they search the same hypothesis space — searching is
searching, whoever ran it — and organisationally hostile. It is not answerable
by writing code, so it is not answered here.

---

## Cost if wrong

**Decision 3 (allocator) is the expensive one to get wrong**, because it sits in
the order path: a netting bug sends real orders that are wrong, and it is the
one component here with no prior art in either reference system to check
against. It is therefore specified to be a pure function from
`(intents, positions, limits)` to orders, testable without a broker, and the
chaos suite gains scenarios for it before it ever routes anything live.

Decisions 1, 2 and 4 are cheap to reverse — they are internal interfaces with
tests. Decision 5 is cheap to reverse but **not cheap to get wrong quietly**,
since a laundered trial is invisible by construction. Decision 6 is deferred by
design.
