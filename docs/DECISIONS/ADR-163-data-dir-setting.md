# ADR-163 — One setting for where data lives

**Date:** 2026-11-12. **Status:** accepted.

- **Context.** 328 `Path("data/...")` literals in 201 modules assumed every process runs from the repository root on one Mac. A container, a server, a second machine or a per-user data folder (the multi-user platform, issue #113) cannot work with that.
- **Options.** (a) Leave the literals and bind-mount the repo's `data/` in containers; (b) a settings object threaded through every function; (c) one environment variable read in one module, with the old relative path as the default.
- **Choice.** (c): `eulerlab.paths.data_path(...)` reads `EULERLAB_DATA_DIR`, default `data` relative to the working directory. A hygiene check (`data-literal`) refuses new literals under `src/`.
- **Why.** Byte-identical behaviour on the Mac today; one line in a compose file tomorrow; no signature changes across 198 files. (a) ties data to the checkout, (b) is a rewrite.
- **Cost if wrong.** A module that reads the setting at import before `.env` is loaded gets the default; `paths` loads `.env` itself to close that, and `tests/test_paths.py` pins the rule.
