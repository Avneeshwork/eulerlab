# ADR-004 — Zerodha Kite Connect as the single live data source

**Date:** 2026-08-18 · **Sprint:** 0 · **Status:** accepted

**Context.** Sprint 2's options-chain recorder needs a live feed for Nifty and
Sensex full chains at a 5-second cadence. Nobody sells cheap Indian option-chain
history with clean timestamps, so this data has to be recorded from day one —
every day not recorded is a day that cannot be bought later at any price.

**Options.** (a) Dhan, free API. (b) Zerodha Kite Connect, ₹500/mo. (c) Both,
₹500/mo total, giving two independent sources.

**Choice.** (b), Kite Connect alone. Operator decision, 2026-08-18.

**Why.** Kite is the best-documented and most widely used of the Indian retail
APIs, which matters for a component that must run unattended every trading day
and whose failure mode is silent data loss. Option (c) was recommended — two
sources catch vendor errors that otherwise surface months later disguised as
alpha — and was declined; one feed is the accepted trade-off.

**Cost line** (required by `CLAUDE.md` cost discipline): **₹500/mo.** It
replaces nothing, because no free source provides timestamped full-chain
snapshots we control — the NSE archives are end-of-day only. **No measurement
justifies it**, and there cannot be one: the argument is irreversibility, not
efficiency. This is the project's first recurring cost.

**Cost if wrong.** Low on the money, real on the data. If Kite's rate limits turn
out to forbid a 5-second full-chain snapshot, Sprint 2 stalls until we switch —
so verifying the permitted snapshot rate against Kite's documented limits is the
**first** task of Sprint 2, before any recorder code is written.

**Revisit when:** the quality engine (Sprint 6–7) flags anomalies that a single
source cannot adjudicate. At that point adding Dhan as a second free feed costs
nothing but the integration, and option (c) becomes available again.
