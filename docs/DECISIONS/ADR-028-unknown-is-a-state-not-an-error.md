# ADR-028 — UNKNOWN is an order state, not an error

**Context.** A send has three outcomes: it landed, it did not land, or we do
not know. The third is common — a timeout, a connection reset, a process
killed between the write and the response — and most order systems model only
two, handling the third by picking one.

**Options.** (a) Two states, treat a timeout as a failure and retry.
(b) Two states, treat a timeout as a success. (c) A third state, `UNKNOWN`,
that only a broker query can leave.

**Choice.** (c). `UNKNOWN` is reachable from `INTENT` and `SENT`, and the only
events in the transition table that leave it are `QUERY_*`. `QUERY_FAILED`
maps `UNKNOWN` back to `UNKNOWN`, so an unreachable broker leaves an order
unresolved indefinitely rather than resolving it by default.

**Why.** Both two-state readings cost money in opposite directions: retrying
double-sends an order that is already resting; assuming success leaves a
position we do not hold. There is no safe default, so the machine refuses to
have one. `tests/test_oms_states.py` asserts the property over the whole
table, not over chosen examples, so a future row cannot add an assumption.

**Cost if wrong.** Orders can pile up in `UNKNOWN` when a broker is
unreachable, and nothing trades until they resolve. That is a deliberate stop,
and the kill switch's `max_unresolved_orders` limit turns it into an explicit
halt rather than a silent stall.
