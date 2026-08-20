# ADR-026 — Price the search before running it

**Date:** 2026-08-19 · **Sprint:** 15 · **Status:** accepted

**Context.** `docs/AI_BUILD_PLAN.md` warns that *an AI that can generate 100
strategies a month against a leaky validation process is a machine for losing
money efficiently.* Sprints 13 and 14 removed the leak. What remains is
arithmetic that is easy to forget: every hypothesis evaluated raises the
Deflated Sharpe bar for **all** of them, including ones already assessed.

**Options.** (a) Generate hypotheses freely and let the gate sort it out.
(b) Cap the number by policy. (c) Price each search before running it and
refuse ones the available history cannot support.

**Choice.** (c).

**Why.** (a) is the failure the build plan names. The gate would hold, but each
new hypothesis silently makes every existing candidate harder to justify, and
nobody notices because the cost lands on other people's work. (b) puts an
arbitrary number in place of a real constraint.

Under (c) the constraint is the one that actually binds: after this search,
would the history we hold still be able to distinguish a good strategy from
the best of the noise? `make scout PROPOSE=n` answers before anything is
generated, and refuses outright when the answer is no.

The numbers make the case better than the argument does. At the ledger's
current 17 entries a candidate must beat a Sharpe of **1.83** from pure noise.
The build plan's own target of "first 20 hypotheses through the gate" would
raise that to **2.16** — and the best real Sharpe this project has produced is
**1.27**. Running that search as stated would make it near-impossible for any
of the twenty to pass, which is worth knowing before writing them rather than
after.

**Generated-but-untested hypotheses count.** This is the part that gets
argued with. If ten cards are written and only the three most promising are
validated, the selection has already happened — the discarded seven informed
the choice. Excluding them understates the search in the flattering direction,
which is the one direction that matters.

**Cost if wrong.** The affordability test could be too strict and block useful
work. It is a printed refusal rather than an enforced one — `scout` declines to
draft, but nothing stops a deliberate override, and the operator owns that
call. What the check guarantees is that the cost is stated before it is
incurred, not that it is never incurred.
