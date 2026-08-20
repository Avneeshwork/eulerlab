# ADR-022 — Engine self-tests are part of `make verify`, and prove they can fail

**Date:** 2026-08-19 · **Sprint:** 12 · **Status:** accepted

**Context.** The build plan calls the backtester self-tests *"the most
important gate in the project"*. Every other check here asks whether the data
is right; this one asks whether the engine is right, which matters more,
because a wrong engine does not produce obviously wrong answers — it produces
plausible ones. A data gap announces itself. A P&L that is quietly 2% generous
does not, and every strategy decision downstream inherits it.

**Options.** (a) A separate `make test-engine` the operator remembers to run.
(b) Ordinary pytest cases alongside everything else. (c) A named gate inside
`make verify`, plus a mutation suite that breaks the engine on purpose.

**Choice.** (c).

**Why.** (a) is a gate that gets skipped on exactly the day it would have
caught something. (b) buries it: "676 passed" says nothing about whether the
accounting invariants specifically held, and the operator's whole interface to
this project is one command and one page. (c) puts a line in the table that
says `engine PASS`, and it is cheap to make mandatory — the tests run on
synthetic worlds with no network and no real data, so there is no reason to
defer them.

The synthetic worlds are the substance of the decision. Correctness is checked
against situations whose answer is known by construction — a flat market where
any P&L must be cost and nothing else, a planted alpha the engine must
recover — rather than against real data where "looks reasonable" is the only
available verdict.

**Every check must be shown to fail.** All ten passed the first time they ran,
which is precisely when a gate is least trustworthy: an assertion that has
never failed is indistinguishable from one that cannot. So a mutation suite
injects the bugs that actually happen — a fee charged twice, a cost skipped on
one side, a timing shift, a non-deterministic result — and asserts the gate
goes red.

**That suite immediately found a hole.** Doubling every cost in the engine
still passed `zero alpha = exact cost drag`, because the cash deduction and
the recorded `fill.cost` both doubled: `loss == costs` stayed true. The
identity was self-consistent and completely wrong. Fixed by adding
`costs match the cost model`, which recomputes every fill's cost from
`eulerlab.costs` through a path the engine does not share — the same principle
as re-deriving a corporate-action ratio from raw text in Sprint 5.

**Cost if wrong.** Low. The gate adds a few seconds to `make verify`. The
golden file is built on a synthetic world rather than the real panel, so it
stays stable as data grows — a golden file that changes whenever a trading day
is appended is one nobody reads — and `UPDATE=1` exists for deliberate
changes, which must be explained in the commit.
