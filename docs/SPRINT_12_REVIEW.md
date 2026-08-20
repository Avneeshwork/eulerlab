# Sprint 12 — backtester self-tests
**Status:** COMPLETE
**Branch:** sprint-12-engine-selftests

## Why this one matters more than the others

Every other check in this project asks whether the *data* is right. This one
asks whether the *engine* is right, and that matters more, because a wrong
engine does not produce obviously wrong answers — it produces plausible ones.
A missing day announces itself. A P&L that is quietly 2% generous does not,
and every strategy decision after it inherits the error.

`make verify` is now **6 of 6** rather than 5: the engine gate runs every
time, not on request. A gate you have to remember is one that gets skipped on
the day it would have caught something.

## What now works (plain English, no jargon)

Ten checks, run against **synthetic worlds where the right answer is known in
advance** rather than against real data, where "looks reasonable" is the only
available verdict:

- **On a market where no price ever moves, a trading strategy must lose
  exactly what it paid in fees** — to the paisa, not approximately. This is
  the sharpest check here because it has one right answer and no tolerance to
  hide inside. It currently loses ₹78,113.65 over 365 trades, and that number
  matches the fees exactly.

- **Plant a profit and the engine must find it.** Five stocks are made to rise
  at a known rate; a strategy holding them recovers 67.4% against a planted
  67.8%. An engine that *cannot* find profit that is provably there would
  silently reject every real strategy — the expensive failure, because nothing
  about it looks broken.

- **Plant nothing and the engine must find nothing.** Holding the flat stocks
  in the same world earns zero.

- **Accounting is checked after every single trade**, not at the end. An
  end-state check passes when two errors cancel.

- **Same input, identical output**, both engines — and a committed reference
  file that must not drift. Any change that moves it has to be deliberate and
  explained.

## The part I want to draw your attention to

All ten checks passed the first time they ran. **That is exactly when a gate
is least trustworthy** — an assertion that has never failed is
indistinguishable from one that cannot fail.

So I wrote a second suite that breaks the engine on purpose — charging a fee
twice, skipping a fee on one side, shifting the timing, making results
non-deterministic — and asserts the gate goes red for each.

**It immediately found a hole.** Doubling every fee in the engine still passed
the "must lose exactly what it paid" check. Both the cash deduction and the
recorded fee doubled, so *loss = fees* stayed true. The books were perfectly
self-consistent and completely wrong — the engine would have reported a
strategy paying twice the real costs as correctly accounted.

Consistency is not correctness. Fixed by adding a tenth check that recomputes
every fee independently, from the cost model, through a path the engine does
not share. Same principle as Sprint 5, where a corporate-action ratio is
re-derived from the raw text so a parser reading it backwards cannot confirm
itself.

## A second flaw, found in Sprint 8's work

Wiring the gate in turned an existing test red, and it turned out that test
had been passing by luck.

Sprint 8's IC harness has two anchors: a feature that *is* the future must
score 1.0, and pure noise must score ~0. The noise fixture used
`hash(symbol) % 997`. Two things wrong with it:

1. **Python randomises string hashing per process**, so the test passed or
   failed depending on an environment variable — non-deterministic, which the
   project forbids, and useless as an anchor.
2. **A label that is constant per symbol is not noise.** In any fixed panel
   some symbols persistently out-drift others, so a fixed ordering can align
   with them and score a genuine, repeatable IC. Measured here at **t = 4.7**.

A real null has to be re-drawn each period. Fixed, and a second test now
records the trap directly so the fixture is not quietly "simplified" back into
it later.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: 6 of 6, including `engine PASS`
```

```bash
make test-engine
```

Expected: ten PASS rows. The two worth reading are `zero alpha = exact cost
drag` — which prints the exact rupee figure it lost and matched — and `costs
match the cost model`, which is the one the mutation suite forced into
existence.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| Golden file covers one canonical run | A single synthetic strategy on a synthetic world. It catches drift in the common path, not in code that run never touches | as more order types arrive |
| No property-based testing | The assigned reading for this sprint is property-based testing, and these are example-based tests over fixed worlds. Hypothesis would explore inputs I did not think of | worth doing before Sprint 19's OMS |
| Accounting invariants run over 20 fills | Enough to catch a systematic error, thin for a rare one. The cost checks run over 365 | when a cheap way to widen it exists |

## What I could not verify

- **That the gate catches bugs I have not thought of.** It catches every bug I
  injected, which is necessary and not sufficient — and the cost-doubling hole
  is direct evidence that my imagination is the binding constraint. That is
  the argument for property-based testing above.
- **That the synthetic worlds resemble real markets.** They deliberately do
  not. They are constructed so the answer is knowable, which is a different
  goal from realism, and it means the gate says nothing about behaviour in
  conditions it does not simulate.

## Decisions I need from you

1. **Add property-based testing (Hypothesis) now or later?** Option A: now —
   the sprint's assigned reading covers it, and the cost-doubling hole shows
   example-based tests only find bugs their author imagined. Option B: later,
   before the OMS in Sprint 19, where the cost of a missed edge case is real
   money rather than a wrong backtest.
   **My recommendation: B**, but earlier than Sprint 19 — right after Sprint
   13, so the overfitting battery is built on an engine that has been fuzzed.

2. **Should `make verify` also run the data-quality checks?** It now runs
   lint, types, tests, docs, engine and state. `make quality`'s manifest-level
   checks are local and fast. Option A: add them. Option B: leave them out;
   verify should test the *code*, and data health is a separate question.
   **My recommendation: B.** Mixing "is the code correct" with "is today's
   data complete" makes a red build ambiguous, and ambiguous gates get
   bypassed.

## Reading added for you

- **Property-based testing** (SHOULD, 30 min) — assigned for this sprint and
  not yet acted on. The concrete motivation is in this review: the fee-doubling
  bug survived ten hand-written checks and was found only because I went
  looking for holes.

## Next sprint

Sprint 13 — the overfitting battery: CPCV with purge and embargo, Deflated
Sharpe, PBO, MinBTL, and the tamper-evident trial counter. Sprint 11's
eleven-year momentum result has not faced any of it, and that is the sprint
that decides whether it means anything.
