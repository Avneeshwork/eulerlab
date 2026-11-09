# ADR-161: Repo hygiene gate, fast commit hook, hook witness

**Context.** Many agents and Claude threads commit into one shared working tree. The audit of 2026-11-09 found little dead code (2 unused modules, 6 kept alive only by tests, 8 duplicated functions) but a commit hook that ran the whole test suite (several minutes, against other threads' half-done edits), so commits were made with `--no-verify` and nothing recorded it. Nothing stopped new clutter either: two ADRs share 095, two research notes share 024, a stale `pnpm-lock.yaml` and a log file were tracked.

**Options.** (a) A rule in CLAUDE.md only. (b) Block `--no-verify` (impossible; git has no hook for it). (c) Make the commit hook fast enough that nobody skips it, add a ratchet check for new clutter, and log skipped hooks after the fact. (d) Paid or heavy tools (SonarQube, jscpd in CI).

**Choice.** (c). `tools/hygiene.py` fails only on clutter not in `tools/hygiene_baseline.json`. The commit hook runs it with `--staged`, judging only the files being committed, so another thread's half-done work cannot block the commit. The full pytest moves from pre-commit to pre-push and `make check`. `tools/hook_witness.py` marks the tree in commit-msg (git runs it only when pre-commit passed) and compares it in post-commit (which `--no-verify` cannot skip), logging misses to `data/logs/skipped_hooks.jsonl`.

**Why.** Free, local, about one second, and it cannot go red on old debt, so it will not itself become a reason to skip hooks.

**Cost if wrong.** A commit with a broken test can land; `make check` before merging to main and the pre-push hook catch it one step later. Delete the three hooks and the pre-push stage line to revert.
