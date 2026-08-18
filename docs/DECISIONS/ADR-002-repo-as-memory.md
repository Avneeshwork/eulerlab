# ADR-002 — The repository is the memory, enforced by a CI gate

**Date:** 2026-08-17 · **Sprint:** 0 · **Status:** accepted

**Context.** This platform is built by an AI agent across many sessions, each
with a hard memory limit. Between sessions nothing is remembered. Either state
lives in the repository or it is lost, and "lost" here means a system nobody —
human or agent — can explain six months from now.

**Options.** (a) Convention: agree to keep docs current. (b) A CI gate that fails
any commit touching `src/` without a documentation change. (c) A full ADR review
process with sign-off per change.

**Choice.** (b), implemented in `tools/docs_check.py`, with `[skip docs]` as a
documented escape hatch for pure refactors.

**Why.** (a) fails silently and always, because the pressure to skip docs is
highest exactly when the code is hardest. (c) is real overhead for a single
operator. (b) costs about 90 seconds per sprint and makes the failure mode loud.
Critically, the gate is tested against throwaway git repositories in
`tests/test_docs_check.py`, so the gate itself cannot rot.

**Cost if wrong.** Mild friction: an occasional pointless doc edit to satisfy the
check. The escape hatch bounds that, and every use of it is visible in `git log`.
