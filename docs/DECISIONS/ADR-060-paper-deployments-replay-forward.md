# ADR-060 — Paper deployments replay forward through the backtest engine

**Context.** The operator wants strategies paper-trading forward with their own
capital, mimicking live, before any live money (2026-10-07). The Mac drops
offline; days get missed. Research 069.

**Options.** (a) A separate daily loop that holds positions and decides each
day. (b) Replay each deployment from its start date through `event_driven.run`
with the OMS executor, every run; the journal makes past orders idempotent.

**Choice.** (b). `deploy/runner.py`. Capital that cannot buy every name keeps
the top-ranked ones (`deploy/sizing.py`, `fit_capital`). Paper only; live is
refused until the Kite adapter is proven (T-3336) and live limits are set.

**Why.** One code path for backtest, paper and live, as `CLAUDE.md` requires.
Catch-up after missed days and recovery after a crash need no extra code. A
revised past is detected (an order for a traded day that was never placed)
rather than silently traded.

**Cost if wrong.** Each run re-reads the panel (about a minute per run, all
deployments share it). A corporate action on a held name shows as a loss until
the paper broker applies it (S-038). If the panel is revised for a past day,
the deployment halts and needs a human.
