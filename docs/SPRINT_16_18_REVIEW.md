# Sprints 16–18 — the research agent loop
**Status:** COMPLETE. Built as one block because the build plan groups them,
and because the stages are only meaningful together.

## The loop

```
    card  ->  critic  ->  codegen  ->  [operator registers]  ->  battery  ->  gate
             free       free                                    ~40 min    seconds
```

Ordered by cost, so the expensive stages only see candidates the cheap ones
could not dismiss. **The loop stops at registration** — it reads cards,
criticises them, and can build them, but it does not register, validate or
promote anything. An agent that could originate a hypothesis *and* decide it
was worth testing would be selecting on its own output, and the trial counter
would be measuring a search it no longer controlled.

## Sprint 16 — codegen composes primitives, and never writes Python

The refusal is the design (ADR-027). Executing generated source would discard
Sprint 4's firewall: a `Strategy` receiving a `MarketView` can physically see
nothing beyond its date, while arbitrary code can open the panel file
directly. The firewall is structural so that nothing has to *remember* to
respect it, and `exec` is the one thing that breaks that.

So a card declares configurations of existing, tested primitives, and codegen
realises them. An unknown feature **raises** rather than being skipped —
silently building fewer strategies would evaluate a card against a different
set than the one it pre-registered.

**The cost is real: this cannot express a novel strategy shape.** Anything
beyond "rank by a known feature, hold the top N" needs a new primitive written
and tested by hand first. That is a brake on throughput, and given what Sprint
15 measured, throughput is not the constraint worth relaxing.

## Sprint 17 — the critic spends nothing

Every validation run costs a trial and raises the bar for every other
candidate. So the cheapest improvement to the loop is not a better gate — it
is refusing to *spend* a trial on something that cannot pass.

The critic reads only the card and the ledger. **No check consults price
data**, deliberately: peeking at how a hypothesis performs and then deciding
whether to "officially" test it is the oldest way to launder a trial.

On the real H-0002 it raises two concerns without being asked:

```
  CONCERN  one finding, not several   low_volatility, max_drawdown were measured in
                                      Sprint 13 as a single cluster (IC corr >= 0.6)
  CONCERN  own evidence disowned      1 red flag says the supporting evidence cannot
                                      be used. Testing anyway means proceeding on a
                                      case the card itself retracts
  NOTE     bar after this trial       Sharpe 1.85 from noise alone at 18 trials
```

**It is advisory and cannot kill anything.** Making it binding would hand an
automated component veto power over research direction on the strength of
heuristics. It warns; the operator decides.

## Sprint 18 — the weekly report says *why*

The build plan asks for "hypotheses tested, passed, killed, and why". The last
word is the specification: a loop reporting throughput teaches nothing.

```
id       status       cfgs  blk  conc  built  gate      title
H-0001   under_validation    5    0     2    yes  KILL      Cross-sectional 12-1 momentum
H-0002   draft               4    0     2    yes  —         Low-volatility anomaly

  hypotheses    : 2      killed: 1      promoted: 0      never tested: 1
  trials logged : 17     the bar now: Sharpe 1.83 from noise alone
```

Gate verdicts are read from the trial ledger rather than tracked separately,
so the report cannot drift from the evidence.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: 6 of 6, 811 tests
```

```bash
make research
```
Expected: the table above. **The line to read is `the bar now`** — that is what
accumulated searching has cost, and it applies to every future candidate.

```bash
make research CRITIC=H-0002
```
Expected: two CONCERNs and no blockers, ending with "the critic cannot refuse".

```bash
make research LIBRARY=1
```
Expected: the shapes and features a card may reference, and a note that
anything else must be written and tested by hand.

## What is fake right now

| Thing | Why | Removed when |
|---|---|---|
| No novel strategy shapes | Deliberate (ADR-027). New shapes need hand-written, tested primitives | when a primitive is written by hand |
| The critic's checks are heuristics | Cluster membership is hardcoded from Sprint 13's measurement; it will not notice a new cluster | when clustering is recomputed (T-1317) |
| "Own evidence disowned" is phrase-matching | Looks for "cannot be cited" and similar. A card that hedges fluently would pass | a better check, if it becomes a nuisance |
| The loop has never run end to end on a *new* hypothesis | H-0001 predates it; H-0002 is drafted and unregistered | when a card is registered |

## What I could not verify

- **Whether the loop produces good hypotheses.** It has produced one, from a
  human-directed search, and the critic argues against testing it. The loop
  enforces discipline; it does not supply insight, and nothing here should be
  read as evidence that it will.
- **Whether the critic's blockers correlate with actual gate failures.** Only
  one hypothesis has ever reached the gate. The critic raised no blocker on
  H-0001 and the gate killed it — one data point, in the unhelpful direction.

## Decisions I need from you

1. **The critic raised no blocker on H-0001, which the gate then killed.** That
   is one data point and it is the wrong way round. Option A: leave it — the
   critic's job is to catch the cheaply-knowable, and H-0001's failure was
   statistical and only knowable after testing. Option B: add a blocker for
   "the feature cluster's best prior result was below the current bar", which
   would have caught it.
   **My recommendation: A, for now.** Option B would have the critic
   extrapolating from prior outcomes, which drifts toward the outcome-peeking
   the module explicitly refuses. Revisit after more hypotheses reach the gate.

2. **Register H-0002 and run the loop end to end?** Option A: yes — the loop
   has never carried a hypothesis all the way through, and an untested pipeline
   is an assumption. Option B: no — the critic objects, and T-1317 would settle
   the objection cheaply first.
   **My recommendation: B**, unchanged from Sprint 15. Running the loop to
   prove the loop works, on a candidate its own critic argues against, would be
   spending a trial on machinery testing rather than research.

## Next

Sprints 0–18 are complete. Next in the build plan is 19–24: OMS/EMS, order
state machine, idempotent client IDs, reconciler, kill switches, first broker
adapter in paper mode. The `Order` schema from Sprint 11 already carries
`algo_id` and deterministic client order ids for exactly that.
