# ADR-144 — CI runs only on pushes to main

**Context.** Operator, 2026-11-07: GitHub Actions minutes could be billed. CI ran the full suite (about 11 minutes) on every push to every branch and again on each pull request; about 800 runs so far.

**Options.** Manual only; on pushes to main (and by hand); leave it.

**Choice.** The operator chose main only. `ci.yml` triggers on `push` to `main` and on `workflow_dispatch`; branch pushes and pull requests run nothing. `make verify` is run locally before every push.

**Why.** The same eight checks run locally in `make verify`, so CI on branches mostly repeated them.

**Cost if wrong.** A branch or PR can look fine on GitHub without having been checked; a break shows up only after it reaches main, as HISTORY #80 did.
