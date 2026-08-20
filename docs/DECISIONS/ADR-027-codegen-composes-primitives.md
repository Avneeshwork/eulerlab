# ADR-027 — Codegen composes vetted primitives; it never writes Python

**Date:** 2026-08-19 · **Sprint:** 16 · **Status:** accepted

**Context.** The research loop needs to turn a hypothesis card into something
runnable. The obvious reading of "codegen" is an agent emitting strategy source
which is then executed.

**Options.** (a) Generate Python and `exec` it. (b) Generate Python, review it,
then execute. (c) Compose configurations of primitives that already exist and
are already tested.

**Choice.** (c).

**Why.** (a) discards every guarantee beneath it. Sprint 4's lookahead firewall
works because a `Strategy` receives a `MarketView` and can *physically* see
nothing else; arbitrary code can open `price_panel.jsonl` directly. The
firewall is structural precisely so nothing has to remember to respect it, and
executing generated source is the single thing that breaks that property.

(b) sounds responsible and is worse than it looks: review catches what a
reviewer thinks to check, the failure modes here are subtle — an off-by-one in
a lookback window is a lookahead leak and looks like nothing — and a human
reviewing a stream of generated strategies stops reading carefully by the
tenth. It also produces artefacts that cannot be diffed usefully against each
other.

Under (c), a configuration is data. `{feature: low_volatility, top_n: 30}` can
be read in a card, checked by the critic, compared against a prior submission,
and carries the feature library's existing tests behind it. An unknown feature
raises rather than being skipped, because silently building fewer strategies
would evaluate a card against a different set than the one it pre-registered.

**Cost if wrong, and it is a real cost.** This cannot express a genuinely novel
strategy shape. Anything beyond "rank the cross-section by a known feature and
hold the top N" requires a new primitive written and tested by hand before a
card may reference it. That is a hard brake on the loop's throughput.

It is the right trade given what Sprint 15 measured: generating more hypotheses
raises the statistical bar for all of them, so throughput is not the constraint
worth relaxing. If the brake ever becomes the binding limitation, the answer is
to write more primitives by hand — not to start executing generated code.
