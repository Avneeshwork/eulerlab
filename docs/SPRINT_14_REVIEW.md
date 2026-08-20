# Sprint 14 — the promotion gate
**Status:** COMPLETE. Its first act was to kill the project's only candidate.

## What now exists

`mandate.yaml` — **your file**. Every threshold the gate applies, and nothing
else. Written once here; `CLAUDE.md` says I may propose changes in a review
and may not edit it without an instruction in that session, and from now on I
won't.

`src/eulerlab/gates.py` — the logic that applies it, holding no numbers of its
own. A test asserts that no threshold literal appears in the file, so the
separation is enforced rather than promised (ADR-025).

```bash
make gate H=H-0001        # PROMOTE or KILL, with every reason
make gate-acceptance      # feed it 3 overfit strategies; all must die
```

## The gate's first act was to kill H-0001

```
  pass  pre-registration            claim, 5 configurations and 4 red flags declared in advance
  pass  evidence signature          matches
  pass  trial ledger                15 entries, chain intact from genesis
  KILL  deflated sharpe             best 0.086, mandate requires >= 0.95
  KILL  probability of overfitting  60.0%, mandate allows <= 25%
  pass  backtest length             9.8y available vs 1.9y needed (5.2x)
  KILL  stress tests                no stress tests in the evidence pack

VERDICT: KILL — 3 of 7 rules failed
```

That is the right outcome and it was never in doubt after Sprint 13. It is
worth saying plainly anyway: **the only strategy this project has produced is
now dead**, and `CLAUDE.md` says it is not tuned and resubmitted. The rule
exists for exactly this moment.

The third failure is procedural rather than substantive — H-0001's evidence
pack was generated before stress tests existed, so the pack has none. Re-running
`make validate` would fill that in at a cost of forty minutes and would not
change the verdict, which is already sealed twice over on independent
statistical grounds.

## The acceptance test: three overfit strategies, all killed

The build plan's criterion. Each fails differently, because a gate that
catches one kind of overfitting and not another certifies the kinds it cannot
see:

| strategy | how it cheats | verdict |
|---|---|---|
| `NoiseFit` | no information at all, re-drawn each period | **KILLED** — DSR 0.000, PBO 33% |
| `RegimeFit` | works before 2021, random after | **KILLED** — DSR 0.056, PBO 33% |
| `LookaheadFit` | ranks on the most recent move, as a one-bar cheat | **KILLED** — DSR 0.002, PBO 33%, worst regime 12% |

They are run through the **real** battery and the **real** gate — no
hand-written evidence packs, because a gate tested against fixtures I wrote is
a gate tested against my own assumptions.

`LookaheadFit` is the one worth understanding. An overfitting battery is built
to catch results *weaker* than they look; a cheat produces results far
*stronger*, and a gate tuned only for weakness can wave it through. It is here
so that failure mode is tested rather than assumed absent.

## What the acceptance test revealed about itself

**`RegimeFit` passed the regime stress test** — 76% of Sharpe retained,
against a 50% floor. It was killed by the statistical rules instead, so the
headline "all three killed" is true and the reasoning underneath is weaker
than it looks.

The cause is a misalignment I did not design in: the stress splits the panel
at its midpoint, **2020-10-23**, while `RegimeFit`'s defect begins **2021-01-01**.
Three months of live signal sit inside the half that is supposed to be broken,
which is enough to lift it over the bar.

Two honest readings, and both matter:

- The regime check is **coarser than it appears**. A strategy whose failure
  does not align with the midpoint can pass it. A rolling or multi-split
  version would be harder to slip past.
- Defence in depth worked. No single rule caught everything, and the
  overlapping rules caught what the individual ones missed — which is the
  argument for having seven rules rather than one good one.

Recorded as T-1404 rather than fixed here, because fixing a test *after*
seeing which strategy slipped past it is how a gate gets quietly tuned to the
cases in front of it.

## How to check it yourself (3 minutes)

```bash
make verify          # expect: 6 of 6, 774 tests
```

```bash
make gate H=H-0001
```

Expected: the KILL table above, and `holdout: the gate returned KILL; the
holdout is not read for a failed strategy`.

```bash
make gate-acceptance
```

Expected: three KILLED lines and `ACCEPTANCE PASSED`. **If any line says
SURVIVED, stop** — the gate is certifying something it cannot see, which is
worse than having no gate.

## The holdout

Reserved from 2025-01-01, **never read**. The mandate permits exactly one read
and the gate refuses it in two situations: when the verdict is KILL, and when
the single read is already spent. There is deliberately no function anywhere
to un-spend it — the holdout cannot be regenerated, so a second read does not
produce weaker evidence, it produces none.

## What is fake right now

| Thing | Why | Removed when |
|---|---|---|
| Thresholds are conventional, not calibrated | 0.95 DSR, 0.25 PBO, t>3 are standard values, not measured against this market. They are in your file to change | when there is evidence to calibrate against |
| The regime stress can be slipped past — T-1404 | Splits at the midpoint only; a defect that starts elsewhere partially survives. Demonstrated above | a rolling or multi-split version |
| `RegimeFit` and `LookaheadFit` are crude | They fail obviously. A subtler overfit might pass, and none of these test that | ongoing |
| H-0001's evidence lacks stress tests | The pack predates them. Verdict already sealed on other grounds | a 40-minute re-run |

## What I could not verify

- **Whether the gate would promote something real.** It has promoted nothing.
  The passing path is exercised by unit tests, never by a live candidate, so
  it has not met a case where the answer was genuinely uncertain.
- **Whether the thresholds are right.** They are conventional. A too-strict
  gate kills everything and is indistinguishable from a working one until
  something deserving comes along.

## Decisions I need from you

1. **Formally kill H-0001?** The gate has said KILL and the ledger records it.
   Option A: mark the hypothesis `status: killed` and move on. Option B:
   leave it open pending the stress-test re-run.
   **My recommendation: A.** The verdict rests on two independent statistical
   failures; the missing stress data cannot rescue it, and leaving it open
   invites exactly the reconsideration `CLAUDE.md` forbids.

2. **The gate has never promoted anything. Is that acceptable?** Option A:
   yes — nothing has deserved it, and a gate that has never passed anything is
   not evidence it is broken. Option B: construct a deliberately *good*
   synthetic strategy and confirm it passes end to end.
   **My recommendation: B, cheaply.** Sprint 12 taught that a check which has
   only ever fired one way is half-tested. A known-good synthetic candidate
   run through the real battery would exercise the promote path and the
   holdout authorisation once, safely.

## Reading added for you

- **Multiple testing and the t > 3 rule** (MUST, assigned this sprint) —
  `mandate.yaml` states the thresholds in plain language, and ADR-025 explains
  why they live there rather than in code.

## Next sprint

Sprints 15–18 are the research agent loop: paper scout, hypothesis cards,
codegen, critic, orchestrator. Everything built so far exists to make that
loop safe — the gate is what stops an agent that can generate a hundred
strategies a month from being a machine for losing money efficiently.
