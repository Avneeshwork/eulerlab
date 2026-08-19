# Sprint 11 — Tier B event-driven backtester
**Status:** COMPLETE

## The two engines agree exactly

`CLAUDE.md` requires one `Strategy` interface used unchanged by Tier A, Tier
B, paper and live. That is now an executable claim rather than an intention.
The same strategy object — no wrapper, no adapter, no `isinstance` — runs in
both engines, and over 1,587 days their equity curves differ by **8.05e-16
relative**, which is machine epsilon.

`make backtest` runs both and reconciles them every time. If they ever diverge
beyond floating-point noise it stops and says so, because both share one
strategy and one cost path, so a real difference is a bug in one of them
rather than a modelling choice.

## What Tier B does that Tier A cannot

Tier A collapses "decide, trade, own" into one step. Tier B separates them —
bar, decision, order, fill or rejection, portfolio — which is the same
sequence a live session runs. On the 11-year momentum run:

- **2,837 orders placed, 2,129 filled, 708 rejected.** Tier A silently skipped
  those 708; Tier B records that the instrument did not trade that day, which
  is what a broker would have told us.
- Every order carries a **deterministic client order id** derived from
  `hash(strategy_id, signal_day, symbol, seq)`, so a retry cannot double-send.
  That property is worthless if it exists only in live code, because then the
  backtest never exercises it.
- `algo_id` is on the order schema from day one, nullable and unused, per the
  compliance stub.
- Realised P&L and costs accumulate as fills happen rather than being derived
  at the end. Sprint 12 can only assert against what this records, and a
  derived number agrees with itself by construction.

## The finding: Sprint 10's conclusion was wrong

The panel now covers **2015–2026 instead of 2023–2026**, and that changes the
answer completely:

| window | | annualised | max drawdown | robust Sharpe |
|---|---|---|---|---|
| 2023–2026 | buy & hold | +10.1% | −20.0% | — |
| | momentum_12_1 | +3.0% | −42.2% | 0.20 |
| **2016–2026** | buy & hold | +7.3% | −41.9% | 0.59 |
| | **momentum_12_1** | **+18.4%** | **−31.6%** | **1.35** |

Sprint 10 concluded "a strong IC did not produce a good strategy". Over eleven
years momentum beats buy-and-hold by **eleven points a year with a smaller
drawdown**. The three-year window was a bad one for momentum and I drew a
confident conclusion from it.

What makes that worth dwelling on: Sprint 10's own review listed "three years
is one regime" under what it could not verify — and then stated a headline
that depended on exactly that. Naming a limitation did not stop me acting as
though it were not there. The review has been corrected in place rather than
quietly amended.

**And the corrected number is still not evidence of edge.** Twelve-month
momentum working in Indian equities over eleven years is among the most
documented effects in the literature; finding it means the engine works. It
has not met an overfitting battery, a holdout, or a promotion gate, and one
strategy on one configuration is one trial.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: all green, 664 tests
```

```bash
make backtest STRAT=buyhold
```

Expected: the control, +7.3% annualised over eleven years, and a
reconciliation block reporting `agree: True`.

```bash
make backtest STRAT=rank FEATURE=momentum_12_1
```

Expected: +18.4% annualised, 708 rejections, and `max difference` around
1e-16. **The reconciliation line is the one to read** — if it ever says
`agree: False`, no number above it should be believed.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| Only market-on-close orders | Limit and stop orders are what the lifecycle exists to support, but nothing needs them yet and an untested order type is worse than an absent one | when a strategy needs one |
| No partial fills or queue position | Modelled as all-or-nothing. Real rejection is modelled; real *partial* fill is not | with the impact model |
| No market impact | Still deferred from Sprint 9. Every result involving a thin name remains optimistic | before any sizing work |
| Costs assume delivery rates | Both engines hold overnight. An intraday strategy needs the intraday branch wired through | when one exists |

## What I could not verify

- **Whether the eleven-year result survives an overfitting test.** It has not
  faced CPCV, a deflated Sharpe, or a holdout. That is Sprint 13, and it
  exists precisely because a good-looking eleven-year backtest is not enough.
- **Whether the −31.6% drawdown is survivable in practice.** The engine has no
  concept of a margin call, a risk limit, or an operator losing their nerve.

## Decisions I need from you

1. **Re-run the IC sweep on the eleven-year panel?** Sprint 8's conclusions —
   including "ten features are really three findings" — were all computed on
   the three-year window, and this sprint just demonstrated how much that
   matters. Option A: re-run and revise. Option B: leave it; Sprint 13 will
   re-test survivors anyway.
   **My recommendation: A, and soon.** The independence clustering in
   particular may look quite different across a crash and a recovery, and it
   is cheap now that the panel is cached.

2. **Impact model before Sprint 12?** Option A: yes — Sprint 12's invariants
   would then cover it. Option B: no, Sprint 12 is the most important gate in
   the project and should not wait.
   **My recommendation: B.** Get the gate in place, then add impact and let
   the gate check it.

## Next sprint

Sprint 12 — backtester self-tests: accounting invariants per event,
known-alpha recovery, zero-alpha equalling exact cost drag, determinism,
golden files. The build plan calls it the most important gate in the project,
and this sprint's `Portfolio` was built to be asserted against.
