# Sprint 15 — paper scout and hypothesis cards
**Status:** COMPLETE

## The number this sprint exists to put in front of you

```
  hypotheses already evaluated : 17
  a candidate must beat        : Sharpe 1.83  (today)
                                 Sharpe 2.16  (after 20 more)
```

The build plan's target for this phase is *"first 20 hypotheses through the
gate."* Running that search would raise the bar every candidate must clear
from **1.83 to 2.16** — and the best real Sharpe this project has produced is
**1.27**.

So the plan as written would make it near-impossible for any of the twenty to
pass. That is not a flaw in the gate; it is what searching costs, and it is
far better known before writing twenty cards than after. `make scout
PROPOSE=n` prints it before anything is generated and refuses outright when
the available history could no longer support a claim afterwards.

## What now works (plain English, no jargon)

- **`make scout PROPOSE=20`** tells you what a search would cost before you
  run it. Every new hypothesis makes *every* candidate harder to justify,
  including ones already assessed, because the statistics divide by how many
  things were tried. That cost is invisible unless something prints it.

- **Hypothesis cards are specs, not summaries.** A card fixes the claim, the
  configurations that may be tried, and the objections — before any evidence
  exists. That is what makes it testable: a claim you can reword after seeing
  the numbers is not a claim.

- **The validator rejects red flags that are really hedges.** "Markets can
  change" complies with the letter and commits to nothing. A red flag has to
  name a number, a mechanism, or a specific finding from this project, or it
  is refused. The whole point of writing objections down in advance is that
  they are the ones you would otherwise talk yourself out of.

- **Nothing registers itself.** Cards are written as `status: draft` and are
  inert. An agent that could register and validate its own hypotheses would be
  marking its own homework.

- **A card without a real source is refused.** `CLAUDE.md` forbids inventing
  one, and a fabricated citation inside a pre-registration would corrupt the
  single artefact the gate depends on.

## H-0002, drafted from real sources

Low-volatility anomaly in Indian equities — repeatedly documented on NSE data
(research note 014, sources cited with fetch dates). Drafted, **not
registered**.

Its own red flags are the interesting part, because they argue against it:

- The supporting evidence from our Sprint 8 — an IC t-statistic of **+5.78**,
  the best of the ten seed features — **cannot be used**. It was computed on
  raw prices and a three-year panel, both since fixed and neither recomputed
  (T-1317). Citing it would mean using a number known to be wrong because it
  points the right way.
- Sprint 13 measured this cluster at internal IC correlation **+0.86 to
  +0.95**, so four configurations are closer to one finding than four.
- Low-volatility books concentrate in large liquid names — the cohort that
  returned only **+4.6%** annualised in our own control. The anomaly may hold
  against zero and not against that.

Whether it is worth registering is a real question, and the arithmetic above
says the answer may well be no.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: 6 of 6, 781 tests
```

```bash
make scout PROPOSE=20
```

Expected: the cost table above. **The two Sharpe figures are the point** — if
the "after this search" number exceeds anything the project has ever produced,
the search is not worth running as specified.

```bash
cat hypotheses/H-0002.yaml
```

Expected: `status: draft`, four configurations, four specific red flags, a real
source URL and fetch date.

## What is fake right now

| Thing | Why | Removed when |
|---|---|---|
| The scout does not search the web itself | Finding candidate papers is human-directed; what is automated is the discipline applied afterwards. An agent conjuring its own citations is the failure mode this most needs to avoid | possibly never, deliberately |
| Sources are abstracts, not full texts | Research note 014 says so. The card claims nothing beyond what the abstracts state | when a paper is actually read |
| The affordability refusal is advisory | `scout` declines to draft, but nothing prevents a deliberate override, and the operator owns that call | it is a stated cost, not a lock |
| The red-flag check is crude | Regex for numbers, named mechanisms, and project references. It will occasionally reject a genuine objection that happens to be briefly worded | a better check, if it becomes a nuisance |

## What I could not verify

- **Whether H-0002 is worth testing.** Deliberately unanswered. The evidence
  that would decide it is exactly the evidence that costs a trial, which is
  the tension this sprint makes visible rather than resolves.
- **Whether the red-flag validator catches subtler hedging.** It catches the
  obvious cases; a fluent, specific-sounding but empty objection would pass.

## Decisions I need from you

1. **How many hypotheses should the research loop actually generate?** The
   build plan says twenty. At the current ledger that pushes the bar to
   Sharpe 2.16, above anything this project has produced. Option A: keep the
   target of twenty and accept that the phase is expected to kill all of them.
   Option B: generate far fewer, higher-conviction candidates.
   **My recommendation: B.** The value of the loop is not throughput; it is
   that each hypothesis is pre-registered and honestly counted. Twenty weak
   cards make one good card unprovable.

2. **Register H-0002, or leave it drafted?** Option A: register and validate —
   it is a real, documented anomaly and the machinery should meet a second
   real case. Option B: leave it drafted until T-1317 recomputes the IC on
   corrected prices, so the decision rests on evidence rather than on a
   figure we know is wrong.
   **My recommendation: B.** T-1317 is cheap, and registering on the strength
   of a number we have already disowned is precisely the reasoning the red
   flags were written to prevent.

## Reading added for you

- **Agent guardrails and trial counting** (MUST, assigned for this phase) —
  ADR-026 is the short version, and the honest summary is one line: the
  guardrail is not the gate, it is the counter, because the gate only sees one
  candidate at a time while the counter sees the whole search.

## Next sprint

Sprint 16 — codegen: turning a registered hypothesis card into a runnable
`Strategy`. The constraint that matters is that generated code must use the
same interface as everything else and gets no privileged access to data, so
Sprint 4's firewall applies to it unchanged.
