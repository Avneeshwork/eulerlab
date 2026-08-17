# ADR-001 — Python 3.12 + uv, with mypy strict on everything

**Date:** 2026-08-17 · **Sprint:** 0 · **Status:** accepted

**Context.** Research code in this project becomes production code — the same
`Strategy` object must run in the backtester and in live execution. So the
research toolchain has to be as strict as the production one from day one, not
tightened later.

**Options.** (a) Python 3.12 + `uv`, mypy strict everywhere. (b) Python + pip/poetry
with typing on library code only. (c) Rust for the execution core now, Python for
research.

**Choice.** (a). Python 3.12 with `uv` for dependency management, `ruff` for lint
and format, `mypy --strict` over `src/`, `tools/` and `tests/`, `pytest` with
`filterwarnings = ["error"]`.

**Why.** `uv` resolves and installs in seconds and produces a committed lockfile,
which is what makes a six-month-old backtest reproducible. Strict typing over
*tests* as well as source is unusual, but tests are where the data contracts get
exercised, and an untyped test is where a wrong assumption hides. Rust (option c)
is the right answer at Tier 3 latency; this project is explicitly Tier 1–2, so
paying that cost now buys nothing.

**Cost if wrong.** Low and recoverable. If mypy strict proves too slow to work
with, relaxing it is a config change. The genuinely expensive mistake would be
the reverse — starting loose and trying to add types over a year of code.
