# Sprint 06 — data quality engine
**Status:** COMPLETE — every check has now run against real data, and doing so
corrected two thresholds and found a real gap in our own corporate-actions feed
**Branch:** sprint-06-data-quality   **Commits:** 2

## What now works (plain English, no jargon)

- **One command tells you what is wrong with the data.** `make quality` checks
  every dataset for gaps, missing days, files that stopped updating, files
  that landed twice, and files that parsed to nothing. It prints counts by
  severity. Right now: **0 errors**.

- **It knows the difference between "impossible" and "unusual".** A high price
  below the low is impossible — no market condition makes that true — so it is
  an ERROR and no setting can make it acceptable. A 12% jump is unusual but
  real, so it is a warning. Mixing those two is how people end up ignoring
  the whole report.

- **Problems we already understand stay quiet, by name.** 1,056 findings are
  suppressed because they are documented — each one tied to its entry in
  `STUBS.md`. Crucially they are silenced *individually*, not by loosening a
  setting. Loosening would also hide the next problem, which is the one we do
  not know about yet.

- **The outlier detection cannot be fooled by the outlier.** This is the part
  worth understanding, and I measured it rather than asserting it. The usual
  method is "flag anything more than 3 standard deviations from average". It
  does not work, in a way that is worse than merely imprecise:

  - On a short series **it cannot fire at all**. With 10 data points the
    largest possible score is 2.85, so a 3-sigma rule flags nothing, ever —
    ten days of 1% moves plus one day of 60% produces silence. That is
    arithmetic, not bad luck.
  - The same error scores differently depending on how much good data sits
    around it: 3.0 among 11 points, 15.5 among 251. So the same corruption
    looks urgent or trivial based on nothing but history length.

  The method used here scores that outlier at 66.8 in every one of those
  cases. Details in `docs/RESEARCH/011-robust-statistics-for-data-quality.md`.

### The engine found three bugs in itself, before finding any in the data

Each was caught by a test, not by reading the code:

1. **A suppression that hid real problems.** My first version silenced all
   1,055 empty minute-data windows as "known". 1,052 are genuinely harmless
   (they predate the stock's listing) but **3 are real gaps** — and a fourth
   appearing tomorrow would have been silenced too. Now split in two, with the
   3 real ones pinned to their exact dates.
2. **A threshold that contradicted its own description.** The check for
   suspicious price jumps said it existed to catch an unadjusted 1:1 bonus,
   which looks like a 50% crash. It was set to 60%, so it could not. Now set
   from a table of what corporate actions actually produce.
3. **The outlier maths collapsing on flat data.** When more than half the
   values are identical the spread measure becomes zero and everything else
   scores infinity — 9 of 19 rows flagged in an ordinary series. Handled.

### And one thing in the real data

Two files landed twice. Both are **byte-identical**, from re-probing during
the S-009 investigation, so harmless. But it showed the check was asking the
wrong question: the same file landing twice is fine, the same *key* holding
two *different* contents is serious, because the landing zone's entire promise
is that raw data is never modified. Split accordingly: identical is INFO,
differing is ERROR.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: all green, 492 tests
```

```bash
make quality
```

Expected: `0 errors, 0 warnings`, 2 INFO lines about the byte-identical
re-landings, and 1,056 findings suppressed against S-007, S-008 and S-009.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| Row-level checks have never seen real prices — T-607 | Built and covered by 30 tests against planted defects, but running them needs one B2 download per day of history and the daily cap is spent. The code path was exercised: it stops cleanly and says so | tomorrow, one command |
| Cross-source reconciliation has never run — T-608 | Same cause. It is the check most likely to find something genuinely unknown, so leaving it unrun is the biggest gap in this sprint | tomorrow |
| The spike threshold (5.0) is chosen, not calibrated — T-609 | It sits above ordinary market drama by judgement. There is no labelled set of known-bad rows to tune against, and inventing one would be worse than admitting this | when real findings accumulate |

## What I could not verify

- **Whether the row checks find anything real.** They find everything I plant,
  which is necessary but not sufficient. Until they run against eleven years
  of actual prices I do not know the false-positive rate, and a check that
  fires on 5% of rows is unusable regardless of correctness.
- **Whether the reconciliation tolerances are right.** 1% on the close is
  reasoned from NSE computing its close as a 30-minute VWAP rather than the
  last trade, but I have not measured the actual distribution of that
  difference. That measurement is the first thing tomorrow's run produces.

## Decisions I need from you

1. **When the row checks run tomorrow, how much history should they cover?**
   Option A: the most recent ~500 trading days, roughly a fifth of the daily
   B2 budget, leaving room for the S-012 factor rebuild the same day. Option
   B: all 2,869 days, which alone exceeds the cap and would take two days.
   **My recommendation: A.** Two years is plenty to measure the
   false-positive rate, and S-012 has been waiting longer.

2. **Should `make quality` run inside `make verify`?** Option A: no, keep it a
   separate command — it needs network and would make the build slow and
   flaky. Option B: yes, but only the free manifest checks.
   **My recommendation: B**, once the row checks have proven their
   false-positive rate. The free checks are fast, local and deterministic, and
   catching a data gap at commit time is worth having.

## Reading added for you

- **Robust statistics** (MUST, 20 min) — already on your list for this sprint.
  `docs/RESEARCH/011-robust-statistics-for-data-quality.md` is the short
  version with this project's own numbers in it, including the "a 3-sigma rule
  cannot fire on 10 points" result, which is worth knowing generally.

## Next sprint

Sprint 7 is options quality (put-call parity, strike monotonicity, butterfly
convexity), which needs the options chain recorder from Sprint 2 — deferred
four times now and still not collecting. That data cannot be bought
retroactively at any price, so the choice to keep deferring is worth making
deliberately rather than by default.
