# Runbook — `make verify` is red

**Symptom.** You ran `make verify` and one or more rows printed `FAIL`.

**First rule: do not continue to the next sprint.** A broken harness in one
sprint poisons every sprint after it, because every later "green" is measured by
the thing that is currently broken.

The failing check's full output is printed underneath the table. Paste that into
the session and stop there — that is the whole of your job here.

---

## Reading the table

```
CHECK       RESULT   DETAIL
lint        PASS     0 issues, format clean
types       PASS     0 errors in 11 files
tests       PASS     27 passed
docs-check  PASS     all src changes have docs
state       OK       Sprint 0 complete, next: Sprint 1 — NSE EOD ingest
```

| Row | What it means when it fails |
|---|---|
| `lint` | Style or a likely bug caught by ruff. Usually fixable with `make fmt` |
| `types` | mypy found a type error. Never "just a type error" in this project — the data contracts are the types |
| `tests` | A test failed. Read which one; the test name states the invariant that broke |
| `docs-check` | Code changed with no documentation change. See below |
| `state` | `STATE.md` is missing a field or drifted into prose it cannot parse |

---

## `docs-check` failed

The message names the offending commit or the working tree and lists the `src/`
files it touched.

- **Normal fix:** write the documentation. An ADR if a choice was made, a
  research note if a fact was looked up, or an update to `STATE.md`.
- **Pure refactor, genuinely no behaviour change:** add `[skip docs]` to the
  commit message. Expect to justify it in the sprint review.

If it fails on a commit that is already made, amend the commit or add a
follow-up doc commit — either satisfies it, since the check looks at the whole
range from `main`.

---

## `state` failed

`tools/state.py` could not parse `STATE.md`. It needs three bold lines, exactly:

```markdown
**Sprint:** 0 — Scaffolding
**Status:** COMPLETE
**Next:** Sprint 1 — NSE EOD ingest
```

**Fix `STATE.md`, not the parser.** A `STATE.md` the tooling cannot read is one
the next session cannot resume from, which is the failure this whole design
exists to prevent.

---

## Nothing runs at all

`make: command not found`, or every target errors immediately:

```bash
make install
```

That creates the virtual environment from `uv.lock` and installs the pre-commit
hooks. If `uv` itself is missing, reinstall it:
`curl -LsSf https://astral.sh/uv/install.sh | sh`.

---

## Prevention

`make install` wires up pre-commit hooks that run ruff on every commit, so lint
and format failures are caught before they ever reach `make verify`.
