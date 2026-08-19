# Sprint 10 — Tier A vectorised backtester
**Status:** COMPLETE
**Branch:** sprint-10-tier-a-backtester

## The result that matters

Sprint 8 found `momentum_12_1` scoring an IC t-statistic of **+5.40**,
positive in all three years. I said then it was a sanity check rather than a
discovery. Running it through a backtest:

| | annualised | max drawdown |
|---|---|---|
| **buy and hold** (top 30 by liquidity) | **+10.1%** | **−20.0%** |
| momentum_12_1, top 30 | +3.0% | −42.2% |
| momentum_12_1, top 30, liquidity-screened | +1.2% | −38.2% |

**A strong IC did not produce a good strategy.** It produced a third of the
return with double the drawdown, and screening out the illiquid names made it
*worse*, not better. That is the single most useful thing this sprint
produced, and it is exactly why the build plan puts a backtester after the IC
harness rather than trusting the IC.

Why the two disagree is worth understanding, because it will recur. IC is a
rank correlation across the whole cross-section — every name counts equally,
including two thousand you could never own. A portfolio has to actually hold
things. When the top 30 by momentum includes **SPYL on ₹49,839 of daily
turnover**, a ₹33,000 position is most of a day's volume, and the fill price
this engine assumes is fiction.

## What now works (plain English, no jargon)

- **`make backtest-fast`** turns a signal into an equity curve, applying
  Sprint 9's real Indian costs, in about 25 seconds.

- **`COMPARE=1` runs it twice — with and without costs.** The difference is
  the cost drag, printed directly. For this strategy it is 2.6% of total
  return, which is the whole question Sprint 9 exists to answer.

- **One `Strategy` interface, and the engine never learns a strategy's name.**
  A strategy is handed what it may see and returns what it wants to hold. It
  cannot fetch data, place orders, or compute a cost — so there is exactly one
  cost path in the system, structurally rather than by discipline.

- **The engine states what it cannot do, with every result.** No intrabar
  prices, so no stops, no limits, nothing path-dependent; fills at the *next*
  bar's close, never the decision bar's. A Tier A number read as a Tier B
  number is worse than no number.

### The bug, and how it was caught

The first run reported **−13.1%** with a **−50% drawdown**. For a long-only
top-30 portfolio in a rising market that is not plausible, so I looked rather
than reporting it.

Holdings whose instrument did not trade on a given day were being valued at
**nothing** — their whole value dropped out of the portfolio and reappeared
the next day. On the real panel, 31 of 400 symbols have at least one missing
day inside their own listed span, so this fired constantly. Fixed by marking
positions at their last known price, while still refusing to *trade* an
instrument that did not print. The corrected return is +7.8%.

Worth naming: no test caught this. Disbelieving a number caught it, and the
test came afterwards.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: all green, 647 tests
```

```bash
make backtest-fast STRAT=buyhold
```

Expected: about +27% total, +10% annualised, −20% drawdown. This is the
engine's control — if buy-and-hold in a rising market does not look like that,
nothing else the engine says is worth reading.

```bash
make backtest-fast STRAT=rank FEATURE=momentum_12_1 COMPARE=1
```

Expected: the table above, and the cost drag printed at the end.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| No market impact | Fills happen at the close in unlimited size. For the liquid names this is a small lie; for SPYL at ₹49,839 a day it is a complete one, and it flatters the unfiltered momentum result | Sprint 9's deferred impact model, before any sizing decision |
| No intrabar anything | Structural to a vectorised engine. Stops, limits and path-dependent rules cannot be expressed | Sprint 11 (Tier B) |
| Panel is 2023–2026 | Inherited from Sprint 8. Almost entirely a bull market, which flatters buy-and-hold specifically — the control benefits more than the strategy | T-807 |
| Delivery cost rates assumed | The engine holds overnight, so delivery STT applies. A future intraday strategy needs the intraday branch wired through | when one exists |

## What I could not verify

- **Whether any of these numbers would survive a real fill model.** The
  unfiltered momentum result in particular depends on filling microcaps at the
  close in size, which cannot happen.
- **Whether −38% to −42% drawdowns are the strategy or the window.** Three
  years is one regime. This is the same limitation flagged in Sprint 8 and it
  now has a concrete cost.

## Decisions I need from you

1. **Extend the panel to 2015 before Sprint 11?** Option A: yes — the
   drawdown question above cannot be answered inside one bull market, and Tier
   B will be validated against Tier A, so both inherit the window. Option B:
   no, proceed and extend later.
   **My recommendation: A.** It is one B2 run and it is now blocking
   interpretation rather than just being nice to have.

2. **Add the impact model before Tier B?** Option A: yes — without it, every
   result involving an illiquid name is optimistic in a way no other check
   catches. Option B: after Tier B, since Tier B is where fills become
   explicit anyway.
   **My recommendation: B**, narrowly. Tier B has to model fills properly, so
   impact belongs with it rather than bolted onto an engine that fills at the
   close by definition.

## Reference taken from `~/Documents/Trade`

Two things borrowed, one warning heeded.

- **Borrowed:** the `cost_mode: realistic | replication` switch, which makes
  "does this survive costs?" one flag rather than a rebuild. It is the best
  idea in that codebase.
- **Borrowed:** the Alpha / TM / RM split as separately pluggable pieces —
  adopted in spirit, though Tier A only needs the Alpha half so far.
- **Warning heeded:** `run_backtest()` there is 636 lines and branches on
  strategy class names, and `Optimize.py` brute-forces Strategy × TM × RM with
  no trial counter. That combination is an overfitting machine, and it is
  precisely what the trial counter from Sprint 8 and the promotion gate in
  Sprint 14 exist to prevent. ADR-021 records the interface decision that
  keeps this engine from going the same way.

## Next sprint

Sprint 11 — Tier B event-driven backtester, sharing this exact `Strategy`
interface. When the two disagree, Tier A should be the pessimistic one; where
it is not, that is a bug in Tier A.
