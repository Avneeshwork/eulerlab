# ADR-062 — Speed work must reproduce every output exactly

**Context.** The operator asked for lower latency across the codebase
(2026-10-07), with the condition that no strategy, backtest, cost or paper
decision may change. "Faster and nearly the same" is a different number.

**Options.** (a) Rely on the unit tests. (b) Record every output first —
both engines on 43 strategies, paper runs, deployments, 24 intraday signals, the
API — on a synthetic panel with a fixed hash seed, and require the changed
code to reproduce all of it, compared float by float.

**Choice.** (b), and only changes that pass it. They are: the panel is
streamed and its rows slotted; the factor file is parsed once per version of
the file (`price_factor_events`); both engines share `backtest/history.py`,
which reuses the overlap between consecutive point-in-time windows; the API
derives trading days, symbol counts, coverage and per-symbol histories once
per panel load; boto3 is imported only when a download needs it.

**Why.** Every one of these can be wrong by one ulp and still pass a test with
a tolerance. The comparison has no tolerance. The window reuse also has a
permanent oracle test that keeps the replaced code (`test_backtest_history.py`).

**Cost if wrong.** The synthetic panel has one action per instrument, so the
golden check alone would miss a multi-action error; the oracle test covers
that case. The check uses one hash seed because Tier A's fill order already
depends on it (HISTORY #21).
