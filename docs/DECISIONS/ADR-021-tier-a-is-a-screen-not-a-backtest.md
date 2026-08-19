# ADR-021 — Tier A publishes its approximations; the Strategy never meets the engine

**Date:** 2026-08-19 · **Sprint:** 10 · **Status:** accepted

**Context.** `CLAUDE.md` requires one `Strategy` interface used unchanged by
Tier A, Tier B, paper and live. The operator's earlier system in
`~/Documents/Trade` shows what happens when that erodes: `run_backtest()` grew
to 636 lines and branches on strategy **class names**
(`if strategy_cls.__name__ in ("XauusdOrbFvgStrategy", ...)`), building a
different parameter dict for each. Once the engine knows which strategy it is
running, there is no interface — only a switch statement wearing one — and
every later backtest-versus-live divergence hides inside it.

**Options.** (a) Strategies return orders. (b) Strategies return positions in
units. (c) Strategies return target *weights* and receive only a `MarketView`.

**Choice.** (c), plus a published list of approximations attached to results.

**Why.** (a) bakes the execution model into the strategy, so it cannot be the
same object in Tier A (no order book) and live. (b) requires the strategy to
know capital and prices, which is the engine's business. (c) leaves the
strategy expressing only what it *means* — what to hold — and gives it no way
to express a cost, a fill, or an order. That last part is a mechanism rather
than a rule: the reference system had two cost paths and neutralised one with
a comment reading *"so it can't compute a second, inconsistent cost basis"*.
A comment is not a mechanism. Here there is nothing to disable.

The approximations list is published with every result because Tier A cannot
model a stop, a limit, or anything intrabar, and a Tier A number read as a
Tier B number carries false precision into a decision. They travel with the
output rather than living in documentation.

**Cost if wrong.** Low and visible. If a strategy genuinely needs intrabar
behaviour, Tier A should decline to run it rather than approximate it — that
is Sprint 11's job, and the interface does not change to accommodate it.

**What running it revealed.** Two things worth recording. A valuation bug —
holdings whose instrument did not print that day were silently valued at
nothing, which manufactured a **-50% drawdown** and flipped the headline
return from +7.8% to -13.1%. It was caught by disbelieving a suspicious
number, not by a test, and the test came after. And the substantive result:
`momentum_12_1`, which scored **IC t = +5.40** in Sprint 8, returns **+3.0%
annualised against buy-and-hold's +10.1%**, with roughly double the drawdown.
A strong IC is not a strategy.
