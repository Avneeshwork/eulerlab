# ADR-044 — A sweep winner becomes the strategy, under three conditions

**Status:** ACCEPTED · 2026-08-25

**Context.** `make optimize` sweeps each strategy's parameters and reports the
best beside the median. Until now it only reported. The operator asked for the
optimised parameters to become the strategy — for the tuned value to be what
backtests, paper runs and live signals actually use.

The tension is direct and worth stating rather than managing. `optimize.py`
exists to say that the maximum of N draws from noise rises with N, and that a
sweep reporting only its winner has found the right tail of a sample. Promoting
that winner to be the default is the exact selection the module was written to
expose. Refusing on those grounds would also be wrong: a platform that measures
parameters and then always ignores what it measured has built an expensive way
to produce reports.

**Options.**

1. **Report only, never adopt.** Safe, and what the code did. It makes every
   sweep advisory, which means the published parameter wins by default even
   when nine settings have been evaluated against it and it lost.
2. **Adopt every winner.** What was asked, taken literally. On this run it
   would set new parameters for fourteen strategies whose entire grid lost
   money — where the "winner" is the least-bad loss and adopting it is fitting
   noise with extra steps.
3. **Adopt under stated conditions, and carry the evidence with the value.**

**Choice.** Option 3. Three conditions, each of which rules out a specific way
this goes wrong.

**The trials must have been spent.** `load()` ignores a dry run outright. A dry
run's numbers are identical to a recorded one and it costs nothing, so adopting
from one takes the selection bias while leaving the deflated-Sharpe denominator
unaware that a search happened. That is strictly worse than either not
searching or searching honestly. The sweep behind the current adoptions spent
180 trials, taking the ledger from 12 to 192 and the required t-statistic from
3.00 to 3.24 — a small move only because the mandate's floor of 3.0 was already
binding.

**Nothing is adopted from a losing grid.** Where every setting lost money there
is no winner, only a least-bad loss. Those strategies keep their published
parameters and store an adoption record with `adopted` false and a reason,
because "we looked and found nothing" is a result and deleting it would let the
same ground be re-searched for free.

**The evidence travels with the value.** Every `Adoption` carries the best, the
median, the fill count, the session count and the share of the win sitting
above the median. `stop_atr_mult = 2.0` on its own cannot be read; the same
number beside "best of 9, 23 fills over 58 sessions, median 19,622" can be.

**Derived, never typed.** Adoptions are read from the recorded sweep rather
than hand-written into a table. A typed constant and a re-run sweep drift apart
silently, and the drift favours whoever wrote the constant.

**Consequences.**

`paper_scan.scan_symbol` with no explicit rules now runs adopted parameters.
Sweeps still pass rules explicitly for every candidate, so a sweep never reads
its own previous winner as a baseline — each one measures the same grid against
the paper's values.

The (i) dialog gained a section placed directly after provenance, before the
description. If a parameter has moved off its published value that is the
second thing a reader needs to know. It shows the paper's value beside the
adopted one, and only for parameters the sweep actually moved: a grid regularly
lands on the paper's own value for one of its two knobs, and listing that as a
change overstates the finding.

**What this does not claim.** An adopted parameter is the better guess of the
ones tried. It is not a validated result: none of these clears t > 3.0 or a
deflated-Sharpe probability of 0.95, and several rest on fewer than twenty
fills over 58 sessions. The dialog says so in the same block that shows the
number, rather than in a footnote, because the two facts are only safe to read
together.
