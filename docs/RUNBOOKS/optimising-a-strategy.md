# Runbook — optimising a strategy, and what it costs

**What this is.** The order the four commands run in, what each one spends, and
the two results that are routinely misread. See ARCHITECTURE §5.5 and ADR-044.

---

## The order

```bash
make optimize ONLY=orb_breakout   # sweep, on the market its paper tested
make adopted-results              # measure the chosen setting
make walk STRATEGY=orb_breakout   # test it on days it was not chosen on
```

`make optimize` is **not** part of `make daily`, on purpose. Every candidate it
evaluates is permanent: the deflated-Sharpe probability and the t-statistic both
take the *total* trial count as their denominator, so a sweep raises the bar for
every result this platform has produced or ever will. That is a reason to sweep
deliberately, not a reason never to sweep — so it runs when an operator asks.

Check what a sweep will cost before running it:

```bash
make evidence
```

---

## "the sweep found a winner, so the strategy works"

**Symptom.** A strategy reports a strong best figure and gets promoted.

**Cause.** The maximum of N draws from noise rises with N. A sweep that tries
nine settings and reports the best has found the right tail of nine samples.

**What to read instead.** The **median**, printed beside the best in every row,
and the `best ÷ median` column. `orb_breakout` on RELIANCE returned +31,399
against a median of +4,011 — an eightfold spread that reads as one lucky
parameter. On QQQ, the index its paper actually measures, it returns +25,668
against +19,622. Same code, same window; the gap is the finding.

---

## "PBO is 0.47, so this is overfitted"

**Symptom.** A strategy with good out-of-sample numbers is rejected on its PBO.

**Cause.** A high PBO has two opposite meanings and the ratio alone cannot
separate them.

**How to tell which.** Read the profitable-settings share next to it.

| | PBO | settings profitable OOS | splits profitable | reading |
|---|---|---|---|---|
| `orb_breakout` | 0.47 | 9/9 | 13/15 | parameter does not matter — pick any |
| `ou_reversion_in` | 0.07 | 5/16 | 8/15 | selection is reliable, the strategy is weak |

When every setting works, they perform near-identically, so which wins in sample
is close to a coin toss and PBO climbs toward 0.5 by construction. That is not a
warning about the strategy. `optimize_walk.verdict` states which case applies in
words; read that rather than the number.

---

## "the sweep un-adopted everything"

**Symptom.** After `make optimize ONLY=...`, strategies that were tuned revert
to published parameters, with no error.

**Cause.** Fixed — but worth knowing the shape. `ONLY=` writes a sweep document
containing only what it swept, and both `tuned.load` and `adopted_run` used to
read the newest document as the whole world. A four-strategy run dropped the
twenty already measured.

**Check.** Adoptions are merged across every recorded sweep now:

```bash
uv run python -c "from eulerlab.intraday import tuned; a=tuned.refresh(); print(len(a), 'covered,', sum(1 for x in a.values() if x.adopted), 'adopted')"
```

If that count falls after a subset sweep, the merge has regressed.

---

## "trials spent by this run: 0" — is that right?

Yes, for `make adopted-results`. A trial is a configuration evaluated *in a
search*, and that command re-runs only settings a recorded sweep already
contains, on the same window, to extract a Sharpe from trades already paid for.

It is **not** right for `make walk`, which scans every grid point and records one
trial each. If `walk` ever prints zero, it has stopped evaluating and started
reading something stale.
