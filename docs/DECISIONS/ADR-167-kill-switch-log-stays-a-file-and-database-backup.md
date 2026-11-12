# ADR-167 — The kill-switch log stays a file; the database is backed up as an export

**Date:** 2026-11-12. **Status:** accepted. Part of issue #114 (T-4559, T-4562).

- **Context.** T-4559 planned to move the agent log and the kill-switch log to Postgres. Separately, with the database on, `make agents-backup` copies files and so would miss every row in it.
- **Options.** Kill-switch log: (a) move it like the others; (b) keep it a file. Backup: (c) `pg_dump` to B2; (d) export each stream as JSON lines and send them through the existing content-compared backup, with a loader for an empty database.
- **Choice.** (b) and (d). The agent log moved; the kill-switch log and the trip file stay files, and the backup now sends them as their own trees. The backup exports the database first (`db/export.py`, `make db-export`); `make db-restore` loads an export into an empty database.
- **Why.** `trip()` writes its log line before the trip file, so a database outage would turn a stop into an exception, and the switch is meant to work from a shell with nothing else running (CLAUDE.md: separate process, separate credentials). A dump must come from a client of the server's own major version, which ties the image to the database's; the export needs no client, is readable as text, and only changed streams are sent.
- **Cost if wrong.** Two servers each keep their own kill-switch log; if one shared log is needed, write it to the database after the file, never instead of it. The export reads every row each night; if that grows slow, export only streams whose last seq changed.
