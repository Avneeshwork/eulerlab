# ADR-170 — Each workspace's own keys, sealed in Postgres under one server key

**Date:** 2026-11-12. **Status:** accepted for model keys; broker keys use the same store but are not wired (T-4571). Issue #113, T-4570.

- **Context.** Keys were lines in the server's `.env`. With several workspaces every user's agents would spend the operator's model budget, and a broker key would be everyone's.
- **Options.** (a) A managed secrets service (Vault, a cloud KMS): cost and another service to run; (b) a file per workspace, as `Workspace.credentials` sketched: does not survive two servers; (c) rows in Postgres sealed with one server-held key.
- **Choice.** (c). `accounts/secrets.py`: Fernet (the `cryptography` package, free, already installed by the broker SDKs) under `EULERLAB_SECRET_KEY`, which is in the server's environment and never in the database. `put` and `names` are owner-only API calls; no API returns a value. `secrets.for_env(name)` is the one lookup: `.env` for the default workspace, the workspace's own value for any other, and never a fall-back to the server's. The model client reads its key through it.
- **Why.** A copy of the table or of the nightly export opens nothing without the server key; no new service; one function to audit.
- **Cost if wrong.** Losing `EULERLAB_SECRET_KEY` loses every stored key (owners re-enter them); it is not in the backup on purpose and must be kept separately. Rotating it means re-sealing every row, which is not built. If a KMS is ever required, only `_fernet()` changes.
