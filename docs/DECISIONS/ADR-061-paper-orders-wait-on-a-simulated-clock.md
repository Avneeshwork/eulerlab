# ADR-061 — Paper and deploy runs pace orders on a simulated clock

**Context.** The EMS governor allows at most 5 orders in any one-second window
and waited by really sleeping. In front of `PaperBroker`, which counts nothing,
that sleep was most of a paper run: the golden-output check's paper section
took 632 seconds, the deploy section 150 (2026-10-07).

**Options.** (a) Keep real sleeps. (b) Turn the governor off in paper mode.
(c) Keep the governor, but give it a clock that advances by each wait instead
of blocking.

**Choice.** (c). `ems.Governor.simulated()`, built on `ems.SimulatedClock`,
used by `paper/runner.fresh_oms` and `deploy/runner.make_oms`. Live adapters
keep `time.monotonic` and `time.sleep`.

**Why.** The same window, the same waits and the same refusals run in paper as
live, so a plan too large for the rate limit still fails in paper first. Only
the wall time goes: paper 632s → 50s and deploy 150s → 8s, with every order,
fill and journal entry unchanged apart from timestamps.

**Cost if wrong.** A paper journal's wall-clock timestamps no longer show the
pacing; five orders can share a real second (S-040). The bound itself is still
tested (`tests/test_ems_governor.py`). A simulated wait overshoots by 1µs, as
a real sleep does: without it, a clock landing exactly on the window edge
rounded back inside it and the limit stopped holding.
