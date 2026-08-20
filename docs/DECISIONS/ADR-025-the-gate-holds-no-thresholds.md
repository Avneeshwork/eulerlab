# ADR-025 — The gate holds logic; the mandate holds numbers

**Date:** 2026-08-19 · **Sprint:** 14 · **Status:** accepted

**Context.** `CLAUDE.md` makes `gates.py` and `mandate.yaml` operator-owned and
says a strategy that fails the gate is dead. That rule has to survive the
moment it is inconvenient — when a result is nearly good enough and a reason
to make an exception is available. Rules survive that moment because of how
they are built, not because of how firmly they were written.

**Options.** (a) Thresholds as constants in `gates.py`. (b) Thresholds as
defaults in code, overridable by config. (c) Thresholds only in
`mandate.yaml`, with no default anywhere in code.

**Choice.** (c). A missing mandate raises; a missing key raises.

**Why.** (a) means relaxing a bar is a code edit, which arrives inside a diff
alongside unrelated work and reviews as a refactor. (b) is worse than either
pure option: a default is what runs when config is absent or misspelled, so
the effective threshold becomes whichever is looser in practice, silently.

Under (c), changing what the gate demands means editing a small YAML file that
contains nothing else, owned by the operator, in its own commit. It cannot
happen as a side effect. `tests/test_gates.py` asserts that no threshold
literal appears in `gates.py`, so the separation is enforced rather than
observed.

Two further rules follow the same reasoning:

**The default answer is no.** A check that cannot be evaluated fails. Missing
statistics fail, missing stress tests fail, an empty pack fails. Wrongly
killing a good strategy costs an opportunity; wrongly promoting a bad one
costs money. A gate that treats those as symmetric is not a gate.

**There is no "pass with concerns".** A verdict that can express reservations
will be overruled by whoever reads them, so `Decision` is binary and lists
every reason.

**Cost if wrong.** The thresholds are certainly not perfectly calibrated —
they are conventional values, not measured ones. But calibration is the
operator's to change, in one visible file, and that is the property worth
having. The acceptance test guards the direction that matters: three
deliberately overfit strategies must all be killed, and if any survives the
gate certifies a kind of overfitting it cannot see, which is worse than no
gate at all.
