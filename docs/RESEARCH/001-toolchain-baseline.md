# 001 — What toolchain is actually available on the build machine

**Sprint:** 0 · **Date:** 2026-08-17 · **Confidence:** high (directly observed)

## Question

Before pinning a toolchain, what is actually installed on the machine this
project is built on, and does anything about it constrain the design?

## Sources

Not web sources — this is a local-environment finding, and the source is the
commands themselves, run on 2026-08-17 on macOS (Darwin 25.2.0, arm64):

| Command | Output |
|---|---|
| `git --version` | `git version 2.51.0` |
| `python3 --version` | `Python 3.12.4` |
| `uv --version` | `uv 0.11.19` |
| `make --version` | `GNU Make 3.81` |
| `gh --version` | `gh version 2.74.1` |

Resolved by `uv sync --extra dev` into the committed `uv.lock`:
`pydantic 2.13.4`, `pyyaml 6.0.3`, `ruff 0.16.3`, `mypy 2.3.1`, `pytest 9.1.1`,
`pre-commit 4.6.2`.

## Findings

1. **Python 3.12.4 is present**, meeting the playbook's 3.12+ requirement with no
   install step. PEP 695 generic syntax (`def load[M: _Strict](...)`) is
   available and both ruff and mypy accept it; `src/eulerlab/config.py` uses it.
2. **`uv` is present and network-reachable.** A full resolve-and-install of the
   dev dependency set completed and produced a lockfile. Reproducible
   environments are available from Sprint 0, not later.
3. **`make` is GNU Make 3.81** — the version macOS ships, and old enough that
   GNU Make 4.x syntax must be avoided. The `Makefile` therefore sticks to plain
   targets, `.PHONY`, and `.DEFAULT_GOAL`. Worth knowing before someone reaches
   for `$(file ...)` and gets a confusing error.
4. **`gh` is installed and can create a GitHub repository** when the operator
   decides to. Nothing has been pushed; see the Sprint 0 review, question 1.
5. **`ruff format` reformats Python code blocks inside Markdown files.** Left
   alone it silently rewrites `docs/quant_platform_playbook.md` and
   `docs/AI_BUILD_PLAN.md`, which are reference source material. `docs/` is
   therefore excluded from ruff in `pyproject.toml`. This was found by running
   the tool, not by reading about it.

## Decision

Pin `requires-python = ">=3.12"`. Use uv with a committed lockfile. Keep the
Makefile to Make 3.81-compatible syntax. Exclude `docs/` from ruff.
Recorded as ADR-001.

## What I could not verify

- **CI has never run.** The GitHub Actions workflow is written against
  `astral-sh/setup-uv@v5` and `actions/checkout@v4` but has not executed once,
  because there is no remote. Its correctness is currently an assumption
  (`docs/ASSUMPTIONS.md`, A-004).
- Whether the operator's machine is the machine that will eventually run the
  scheduled jobs, or whether that is the Sprint 2 VPS. Not yet decided.

## Open questions

- Does the operator want a private GitHub repo now (needed to verify CI) or
  later? → Sprint 0 review, question 1.
