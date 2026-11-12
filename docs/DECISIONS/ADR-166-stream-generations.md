# ADR-166 — Order journals in Postgres: a reset is a new generation, not a delete

**Date:** 2026-11-12. **Status:** accepted. Part of issue #114, after ADR-165.

- **Context.** On files, a paper book run with `--reset` and every attribution run start from an empty journal by deleting `orders.jsonl`. The `append_log` table refuses deletes, so the journal could not move to Postgres as it was.
- **Options.** (a) Let the table delete for journals only; (b) give each reset a fresh stream name chosen by the caller; (c) number the resets: generation 1 is the stream as named, a reset starts generation n + 1 under `<name>@n+1`, recorded in an append-only `stream_generation` table (migration 002), and readers see the current generation.
- **Choice.** (c), behind one function, `oms.journal.reset(path, reason)`: on a file it deletes as before; in the database it starts the next generation. A committed insert replaces the fsync as the durable write before the order is sent.
- **Why.** (a) brings back the one thing the table exists to prevent. (b) spreads naming over every caller and loses the link between a book and its earlier runs. (c) keeps every order ever journaled, records when and why each reset happened, and changes no caller but the two that reset.
- **Cost if wrong.** If a generation is ever needed by number (an audit of a reset run), it is `Stream(kind, name, generation=n)`; nothing reads old generations yet. Each append opens a connection, so a long paper replay is slower in the database than on a file; pool connections if a measurement shows it matters.
