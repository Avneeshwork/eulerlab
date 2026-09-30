# ADR-040 — Multi-user, which reverses the founding premise

**Date:** 2026-08-21 · **Status:** accepted (operator instruction)

**Context.** `CLAUDE.md` opens: *"Single operator, single-person capital.
Optimise for correctness and low cost, not scale."* Every cost-discipline rule
in this project descends from that sentence. Earlier in this same session the
operator chose **architecture-ready, not multi-user** for exactly that reason.

They have now instructed the opposite: a multi-user professional dashboard.
This is not an extension of the premise, it is its reversal, and recording it
is the point of this file. `CLAUDE.md` should be amended by the operator — it
is theirs, not mine to edit.

**Choice.** Build real tenancy: workspaces, per-workspace data and credentials,
and an authentication seam. Not simulated, not "ready for later".

---

## The question this forces, and the answer

**Do two users share a trial ledger?**

I said this was the operator's call and it is, but "start working" needs a
default, so here is one with its cost stated.

**Per-workspace ledgers.** Each tenant's search raises only their own bar.

*Why not shared:* statistically, sharing is more correct — the multiple-testing
problem does not care who ran the test, and a thousand users searching the same
hypothesis space really have collectively searched a thousand times. But a
product where one customer's failed exploration permanently raises another
customer's bar cannot be sold, and the first support ticket writes itself.

*What it costs:* the bar is weaker than the statistics justify. A tenant who
runs fifty strategies has genuinely searched fifty times and their bar reflects
that; the *population* of tenants has searched far more, and nothing captures
it. This is a real weakness and it is not solved by pretending otherwise.

*The mitigation that is honest:* within a workspace, count everything —
including the screening the workbench currently performs for free (T-3321).
A per-tenant bar that counts all of a tenant's search is defensible. A
per-tenant bar that only counts the formal runs is not.

---

## What tenancy actually means here

| Concern | Scoped how |
|---|---|
| Landing zone | **Shared.** Market data is not anyone's private property and duplicating 3.5 GB per tenant is absurd |
| Derived panels | **Shared**, keyed by data version |
| Trial ledger | **Per workspace**, and hash-chained per workspace |
| Strategies | **Per workspace**, with a shared read-only public library |
| Broker credentials | **Per workspace**, never in the repo, never in a shared table |
| Kill switch | **Per workspace**, and one global switch that stops everything |

The split matters: sharing data and isolating *evidence* is what makes the
product cheap to run and honest to report.

**Cost if wrong.** High on credentials and the kill switch — a leak across
tenants there is money, not embarrassment. Moderate everywhere else. The
landing zone being shared is the one decision that would be expensive to
reverse, and it is also the one least likely to need reversing.
