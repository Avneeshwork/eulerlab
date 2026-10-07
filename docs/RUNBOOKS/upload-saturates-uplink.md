# The Mac drops offline while uploading to B2

**Symptom.** The machine loses its connection every few minutes while a B2
upload runs (2026-10-07: three drops in six minutes during `make sync-derived`).

**Diagnosis.** `sync_directory` uploads with 12 workers. That suits trees of
many small files, which are bound by round trips. On a tree of a few large
files (`data/derived/`: a 710 MB panel, a 528 MB backup, a 184 MB delivery
table) twelve concurrent uploads fill the uplink, and each reads its whole file
into memory first.

**Fix.** `make sync-derived` uploads one file at a time (`workers=1`). The
upload is resumable: re-running skips anything B2 already holds at the same size.

**Prevention.** Pass `workers=` to `sync_directory` for any tree of large files.
