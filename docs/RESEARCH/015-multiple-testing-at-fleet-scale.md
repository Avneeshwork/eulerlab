# 015 — Multiple testing when the fleet is hundreds of strategies

**Fetched:** 2026-08-20

---

## The question

The operator wants to run hundreds to thousands of strategies across several
asset classes. Every strategy configuration evaluated appends a trial to the
ledger, and the noise bar rises with the trial count. Does the existing
accounting survive that, and if not, what does the literature actually
recommend in its place?

---

## What our own code says

This part needs no external source — it is arithmetic on the function already
in `src/eulerlab/validation/statistics.py`, run directly:

| Trials | Sharpe the candidate must clear |
|---|---|
| 19 (today) | 1.88 |
| 50 | 2.28 |
| 100 | 2.53 |
| 250 | 2.84 |
| 500 | 3.05 |
| 1,000 | 3.26 |
| 5,000 | 3.69 |

The best result this project has ever produced is **1.27**.

These figures reproduce the project's own published numbers exactly — the
ledger's 19 trials give 1.88, and `research/scout.py`'s claim that twenty more
hypotheses moves the bar to 2.16 lands at 2.17 here. So this is the existing
curve, not a new model of it.

**The finding: a flat trial counter makes a large fleet unpublishable by
arithmetic, before any strategy in it is even wrong.** At a thousand
configurations a candidate needs Sharpe 3.26 net of costs to be
distinguishable from the best of a thousand coin flips. Nothing in Indian
equities does that at capacity. The gate would kill the entire fleet, and it
would be right to, given what it was told.

---

## Sources

**Harvey, Liu & Zhu (2016), "… and the Cross-Section of Expected Returns",
*Review of Financial Studies* 29(1).**
Published version fetched from the author's own page,
<https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.PDF>,
2026-08-20. Also NBER w20592, <https://www.nber.org/papers/w20592>.

Findings taken from it:

- It distinguishes **FWER** (family-wise error rate — the probability of *any*
  false positive) from **FDR** (false discovery rate — the expected
  *proportion* of false positives among the discoveries), §3.3.
- It recommends the **Benjamini–Hochberg–Yekutieli** procedure, §3.4.3, over
  Bonferroni and Holm, because FWER control is punishing once the number of
  tests is large while FDR control still admits true discoveries.
- It treats **correlation among test statistics as a first-class problem** and
  builds a model for it, §4 / §4.1 — tests of related factors are not
  independent and must not be counted as if they were.
- It concludes a newly claimed factor should clear a t-ratio near **3.0**
  rather than the conventional 2.0.

The relevance is direct. Our expected-max-Sharpe correction is FWER-shaped: it
asks what the *best* of N pure-noise strategies would score, which controls the
chance of promoting any false positive at all. That is the right instrument for
a handful of pre-registered candidates and the wrong one for a fleet.

---

## What I could not verify

**The clustering method for estimating an effective N.** Two independent search
summaries attribute to López de Prado (2018) a set of techniques for estimating
the effective number of independent trials by clustering correlated strategies
— the Optimal Number of Clusters (ONC) algorithm, hierarchical clustering as a
conservative lower bound, and spectral methods on the correlation matrix's
eigenvalues. **I could not confirm any of this from a primary source.** The
Wikipedia article 404s at the URL search returned, and the Bailey & López de
Prado deflated-Sharpe PDF at
<https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf> extracted badly:
the formulas it yielded (`SR0 = (2−π)^(1/2)·Z_α + γ·ln(N)` and
`DSR = SR·[1 − γ/ln(N)]`) match neither the literature nor our own
implementation, and the accompanying claim that lowering N inflates SR₀ is
backwards — lowering N *lowers* the bar, which is why the incentive runs toward
undercounting. **Nothing from that extraction is used anywhere.** Recorded as
A-020 with a recheck.

This matters because effective-N is the mechanism the ADR leans on. The
*direction* is well supported by Harvey/Liu/Zhu §4, which is fetched and
sound. The specific estimator is not yet sourced.

Encouragingly, the project has already solved this problem once for itself:
`src/eulerlab/features/independence.py` clusters the feature sweep and reports
that ten features amount to roughly three findings. That is the same
computation applied to features rather than strategies, and it was written
without needing the reference above.

---

## A second finding, unlooked-for

`expected_max_sharpe(n_trials, *, variance_of_sharpes: float = 1.0)` — the
`variance_of_sharpes` term is σ²_SR, the dispersion of Sharpe ratios across
the trials actually run, and it **scales the entire bar**. It defaults to 1.0,
that default has never been overridden anywhere in the codebase, and it appears
nowhere in `docs/`.

It is not a harmless default. Measured with the project's own function:

| σ_SR | Bar at 19 trials |
|---|---|
| 0.50 | 0.94 |
| 0.75 | 1.41 |
| **1.00 (assumed)** | **1.88** |
| 1.25 | 2.35 |
| 1.50 | 2.82 |

**The project's best-ever result is 1.27, which sits inside that range.** If
the true dispersion of Sharpes across our trials is below about 0.68, the bar
is under 1.27 and the best result clears it. If it is 1.5, every past verdict
was too lenient. So the assumed 1.0 is potentially the difference between "the
gate has killed everything it has seen" and "something survived" — and that
sentence appears in `README.md`, `STATE.md` and `docs/HISTORY.md` as a settled
fact.

**I assumed this was free to measure and checked. It is not, and the reason is
the finding.** The ledger does not record a Sharpe for most trials:

| Ledger kind | Entries | Carries a Sharpe? |
|---|---|---|
| `ic` | 12 | No — `mean_ic`, `n_periods`, `t_stat` only |
| `gate` | 4 | No — `verdict` and `failed_rules` only |
| `validation` | 3 | Yes — `best_full_sample_sharpe` |

So 3 of 19 entries carry the number, and **all three are the same subject** —
H-0001 at successive stages: 1.0088, 1.0088, 1.2667. That is one hypothesis
measured three times, not a cross-section of strategies. Their naive standard
deviation is 0.149, which would imply a bar of **0.28** and promote nearly
anything. The figure is not merely noisy, it is measuring the wrong thing.

**The one parameter that scales the entire multiple-testing correction is the
one number the ledger does not record.** σ_SR cannot be estimated from the
evidence the project has kept, and no amount of care with the existing data
fixes that — the observations were never written down.

Two consequences. The current bar of 1.88 rests on a constant that cannot
currently be checked against anything. And the fleet work has a hard
prerequisite: **the ledger must record the realised Sharpe of every trial from
now on**, or the correction can never be calibrated no matter how many
strategies are run. That is a schema change to an append-only file, so it
applies going forward only; the 19 existing entries cannot be back-filled.

---

## Decision

Proposed in ADR-035: count trials by **family** with an effective-N correction
for within-family correlation, and control **FDR across families** rather than
FWER across configurations. Operator-owned — `mandate.yaml` and `gates.py` may
not be edited without an explicit instruction, so this is a proposal and
nothing has been changed.

**Confidence: medium.** The problem is certain and quantified from our own
code. The direction of the fix is well sourced. The specific estimator for
effective N needs a primary source before it is implemented.

---

## Open questions

1. ~~What is σ_SR, measured from our 19 logged trials?~~ **Answered, and the
   answer is that it cannot be measured** — the ledger records a Sharpe on only
   3 of 19 entries, all for the same hypothesis. The open question becomes:
   record per-trial Sharpe from now on (a ledger schema change), and until
   enough entries accumulate, what does the operator want the bar scaled by?
   Leaving it at 1.0 is a choice, not a default (A-021).
2. Does an effective-N estimator need strategy *return series* — which means
   every variant must be backtested and stored before the correction can be
   computed? If so, the cache in the fleet architecture is a prerequisite for
   the statistics, not just a performance optimisation.
3. What FDR level q does the operator want? Harvey/Liu/Zhu's t≈3.0 is roughly
   a Bonferroni-flavoured answer for ~300 tested factors; BHY at q=0.05 is
   more permissive and more appropriate here.
4. How are the 19 already-logged trials treated under the new scheme? They
   were not pre-registered into families. Retrofitting them is a judgement
   call, and the honest default is to leave them as one family of 19.
