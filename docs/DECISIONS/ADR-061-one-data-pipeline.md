# ADR-061 — One data pipeline for the button and `make daily`

**Context.** Data fetched with Instruments → Update daily feed never reached the
price panel or the paper books (the button stopped at fetching). The button
could run while `make daily` ran, and both append each day to the same files.
Nothing showed what was missing (2026-10-08, T-4030, T-4032).

**Options.** (a) Keep two routes and document the gap. (b) Have the button shell
out to `make daily`. (c) One step list (`daily_feed.STEPS`) that fetches and
then rebuilds every derived table and the paper books, with `make daily` and
the button sharing a `feed` lock, and a test that fails when `make daily`
grows a step the button does not run.

**Choice.** (c). The button also gets a coverage table (`ingest/coverage.py`,
`GET /api/data/coverage`, `make coverage`). Every appender holds its own lock and
reads its cache inside it. The US panel re-reads only the last two months.

**Why.** (b) would bring pruning and the hour-long fundamentals walk into a
click. (c) keeps one list, refuses overlap, and lets the operator see the
result without reading logs.

**Cost if wrong.** A step that needs a terminal (Kite login) can never be in
the button; it is named in `TERMINAL_ONLY` and shown in the coverage table.
