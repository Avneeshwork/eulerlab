# ADR-196 — The test suite runs in parallel, one worker per test file

**Date:** 2026-11-14. **Status:** accepted; operator's "run in parallel" on 2026-11-14.

- **Context.** The full suite (3,763 tests, 5 skipped) took 19 min 46 s wall time in one process on the Mac (8 cores), and it runs in `make check` and on every push. No single test is slow (the slowest is 5.6 s); the time is spread across the suite.
- **Options.** (a) Keep one process and trim tests. (b) `pytest-xdist` with `--dist load`, tests spread one by one. (c) `pytest-xdist` with `--dist loadfile`, each file kept in one worker.
- **Choice.** (c). `make test`, `make check` and the pre-push hook run `-n auto --dist loadfile`. `make check SERIAL=1` / `make test SERIAL=1` and `SERIAL=1 git push` run in one process.
- **Why.** Measured on the Mac on 2026-11-14 with the daily job running: 2 min 4 s and 2 min 1 s in parallel against 19 min 46 s serial, about 9.8 times faster. Keeping a file in one worker keeps its module fixtures and shared files together. Each worker starts its own throwaway Postgres in its own socket directory, so the database tests do not share. One test leaked process-wide state (`chat._LAST_GOOD`) that the serial order had hidden; it now resets that state itself.
- **Cost if wrong.** A test that depends on another file's side effect passes serially and fails in parallel, or the other way round, and the failure depends on which worker a file lands in. Run with `SERIAL=1` to tell the two apart. Output order is no longer the file order.
