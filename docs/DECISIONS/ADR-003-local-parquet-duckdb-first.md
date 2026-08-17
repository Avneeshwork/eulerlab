# ADR-003 — Parquet + DuckDB on local disk; no ArcticDB, ClickHouse or S3 yet

**Date:** 2026-08-17 · **Sprint:** 0 · **Status:** accepted

**Context.** `docs/quant_platform_playbook.md` §1.4 specifies a full storage
stack: immutable landing zone on S3/MinIO → ArcticDB for curated time series →
ClickHouse for analytics → a feature store → Redis for live state. That is the
correct design at scale. This project has one operator, one person's capital, and
no data yet.

**Options.** (a) Build the playbook stack now. (b) Parquet files in a local
landing zone plus DuckDB for queries, upgrading when a measurement demands it.
(c) A hosted warehouse.

**Choice.** (b). `data/landing/` holds immutable gzipped vendor files; curated
data becomes Parquet; DuckDB is the query engine. `data/` is gitignored. No
server, no cloud account, no monthly bill.

**Why.** The playbook's own cost discipline says buy nothing you can avoid for
the first six months, and the properties that actually matter — an immutable
landing zone, bitemporal columns, reproducibility from raw — are properties of
the *schema*, not of the storage engine. They are preserved under (b) and carry
over unchanged. ArcticDB's API is the same on a local filesystem as on S3, so
that upgrade is a config change when it comes.

**Cost if wrong.** Moderate but bounded. If local disk or single-machine query
speed becomes the constraint, we migrate — and because the landing zone is
immutable and complete, the curated store can be rebuilt from scratch rather than
migrated in place. The trigger to revisit is written down in
`docs/AI_BUILD_PLAN.md` §3: local disk full, or backtests taking hours.
