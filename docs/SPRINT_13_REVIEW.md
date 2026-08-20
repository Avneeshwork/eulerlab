# Sprint 13 — overfitting battery
**Status:** COMPLETE. **The verdict on H-0001 is negative, and that is the
sprint working, not failing.**

## The result

`make validate H=H-0001` put the momentum hypothesis through purged CPCV,
Deflated Sharpe, PBO and minimum backtest length. It does not survive.

| | |
|---|---|
| **PBO** | **53.3%** over 15 paths — *worse than a coin flip* |
| **Deflated Sharpe** | **≤ 0.021** for every configuration (0.95 is the usual bar) |
| Best full-sample Sharpe | 1.01 |
| Expected best Sharpe from **13 worthless strategies** | **1.70** |

That last pair is the whole finding. Given how many things have been tried,
pure noise would be *expected* to produce a Sharpe of 1.70. The best real
result is **1.01** — below what searching this hard would have produced from
nothing at all.

PBO above 50% says something slightly different and equally unwelcome: picking
whichever momentum configuration looked best historically does **worse than
random** at choosing which will do well next. The selection is fitting noise.

**What this does not say:** that momentum is worthless. It says these five
configurations, evaluated on this history, after this many attempts, cannot be
distinguished from luck — and that choosing between them on past performance
is not a skill we have demonstrated.

## Three sprints, three corrections, one direction

Worth stating plainly because the pattern is the point:

- **Sprint 10** concluded "a strong IC is not a strategy" from three years.
- **Sprint 11** extended to eleven years and found momentum returning +18.4%
  a year against buy-and-hold's +7.3%. Sprint 10's headline was corrected.
- **Sprint 13** puts that result through the battery and finds it
  indistinguishable from noise once the search is accounted for.

Each stage was more careful than the last, and each overturned the previous
answer. The lesson is not that the earlier work was sloppy — it is that
**confidence should track the strength of the test, not the appeal of the
result**, and only the last of those three had a test worth the name.

## A red flag the battery surfaced by accident

Two configurations show **excess kurtosis of +101 and +161**, with skew above
+4. A normal distribution has excess kurtosis 0; a typical equity strategy
might reach 5–10. Values in the hundreds mean the return stream is dominated
by a handful of enormous single days.

That is not a subtle statistical point — it means those "Sharpe ratios" are
describing a distribution where the average is nearly meaningless. It is
recorded as an open task rather than investigated here, because it was found
at the end of the sprint and guessing at the cause would be worse than naming
it. My suspicion is microcap prints, which Sprint 10 already flagged.

## What now works (plain English, no jargon)

- **Purged, embargoed cross-validation.** Ordinary cross-validation is invalid
  here: the "answer" for any given day is built from the following month's
  prices, so a training day next to a test day has already been shown most of
  its own answer. Purging removes the overlap; embargo adds a gap for the
  correlation that purging misses.

- **A trial ledger that cannot be quietly edited.** Every statistic gets more
  favourable as the trial count falls, so the count is hash-chained: altering
  or deleting a row breaks every link after it. If the chain is broken,
  `make validate` **refuses to print anything at all**, because a number
  computed from an unverifiable denominator is worse than no number.

- **A holdout that is reserved and structurally unreachable.** The panel is
  truncated once, at the top of the run, so no analysis downstream has the
  option of peeking. 2025 onward has never been read.

- **Red flags written before the evidence.** `hypotheses/H-0001.yaml` fixes
  the claim, the configurations and the known objections in advance. A
  hypothesis you can reword after seeing the result is not a hypothesis.

## Two bugs found, one of them mine twice over

**The leakage check was wrong, and it condemned correct code.** It reported
leakage on 14 of 15 paths. The purging was fine; the *check* derived its
ordering from the train+test days — the timeline *after* purging had removed
the gap — so two dates **42 trading days apart** appeared adjacent. A label
window is measured in elapsed sessions, so it can only be checked against the
real calendar.

**The engines were 14× slower than they needed to be.** Building a market view
handed every feature the full 2,869-day history when the longest lookback in
the library is 253 days. A run went from 95 seconds to 6.9. Strategies now
declare their own lookback, and the engine honours it — the strategy knows the
answer and the engine must not learn strategy internals (ADR-021). Verified
byte-identical output before and after.

## How to check it yourself (5 minutes)

```bash
make verify          # expect: 6 of 6, 190 tests in the validation suite alone
```

```bash
make validate H=H-0001
```

Expected: the table above, ending with the red flags that were declared before
any of it ran. **The line to read is PBO.** Above 50% means the selection
procedure is picking noise, and no Sharpe ratio printed above it should change
that conclusion.

## What is fake right now

| Thing | Why | Removed when |
|---|---|---|
| "In-sample" is not a fitted sample | Nothing is *fitted* here — fixed configurations are evaluated on two date ranges. PBO still measures whether relative ranking persists, but it is not measuring fitting-induced overfitting, and the standard interpretation assumes it is | when a strategy has parameters that are actually estimated |
| Evidence pack is JSON, not the PDF the build plan names | A PDF adds a rendering dependency for presentation only. The hash is what makes it evidence | if you want a PDF |
| Tail truncation of the ledger is undetectable | Hash chaining proves what remains is unaltered; it cannot prove nothing was removed from the end. Stated in ADR-023 rather than implied away | needs an external anchor |
| Stress tests not built | The build plan lists them for this sprint. CPCV, DSR, PBO and MinBTL are in; scenario stress testing is not | next |

## What I could not verify

- **Whether the extreme kurtosis is real or a data artefact.** Found late,
  and it materially affects how the Sharpe ratios should be read.
- **Whether momentum would survive with fewer trials.** The correction is
  driven by 13 recorded attempts. That count is honest and it is also the
  reason nothing passes — which is the correction working as designed, not an
  argument for resetting it.

## Decisions I need from you

1. **The battery says H-0001 does not pass. What happens to it?**
   `CLAUDE.md` is unambiguous: *a strategy that fails the gate is dead; do not
   tune it and resubmit.* Option A: mark H-0001 killed and move on. Option B:
   treat this as a dry run, since the formal gate is Sprint 14 and this is
   Sprint 13's battery rather than the gate itself.
   **My recommendation: A, with the reasoning recorded.** The rule exists
   precisely for the moment when the result is unwelcome and a reason to make
   an exception is available. If it bends now it will bend later.

2. **Investigate the kurtosis before Sprint 14?** Option A: yes — Sharpe
   ratios on a distribution that fat are close to meaningless, and the gate is
   about to be built on them. Option B: proceed; the gate does not depend on
   any specific hypothesis.
   **My recommendation: A.** It is cheap and it affects how every future
   result is read.

## Reading added for you

- **CPCV, Deflated Sharpe, PBO** (MUST, assigned this sprint) — the three
  modules carry the reasoning inline, and `docs/DECISIONS/ADR-023` covers the
  ledger. The single most useful idea: *the expected maximum Sharpe from N
  worthless strategies*, which is 1.70 at N=13 and is the number our best real
  result failed to beat.

## Next sprint

Sprint 14 — the promotion gate as code, with pre-registration and a locked
holdout enforced to a single read. The build plan's acceptance test is to feed
it three deliberately overfit strategies and require all three to be killed.
H-0001 may well be the first honest test case.
