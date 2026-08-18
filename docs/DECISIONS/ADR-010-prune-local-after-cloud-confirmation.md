# ADR-010 — Delete local landing files once B2 confirms them, keep the manifest

**Date:** 2026-08-18 · **Sprint:** 1 · **Status:** accepted

**Context.** The operator's laptop disk hit 394 MB free (198 of 228 GB used,
mostly unrelated to this project) mid-backfill, and the minute-bar job crashed
on `ENOSPC`. Separately, the operator does not want a full local copy of the
landing zone kept indefinitely.

**Options.** (a) Stream to B2 only, never touch local disk. (b) Run the whole
pipeline on a rented VPS instead of the laptop. (c) Land locally as today, then
delete a file once B2 is confirmed to hold an identical copy.

**Choice.** (c). Operator decision, 2026-08-18.

**Why.** (a) drops the atomic-write-then-rename safety net that makes a crash
harmless today — `landing.py`'s write path tolerated the `ENOSPC` crash with
zero partial files precisely because it writes locally first. (b) is the
correct answer for "nothing on my device" in the strict sense, and remains
available later; it was not chosen now. (c) keeps every property already
built — idempotency, checksums, atomic writes — and adds only a size-confirmed
deletion step. It is also cheap: `list_sizes` is one paginated LIST for the
whole bucket, so confirming thousands of files costs a handful of requests.

**The manifest is never edited.** A pruned file is still recorded as landed —
its bytes live in B2 now, not on disk — so nothing downstream that reads the
manifest needs to know or care that the file moved.

**Guard, mirroring the cloud-sync mismatch guard:** a file is only deleted when
the bucket size matches exactly. Not uploaded yet, or uploaded at a different
size, and it stays untouched. The one-off cleanup run on 2026-08-18 found 5,168
confirmed of 14,894 local files, zero size mismatches, and freed 1.83 GB.

**Restoring is the other half.** Pruning is only safe if restoring is easy, and
it is not easy if it does not exist — so `make restore-local` pulls files back
from B2 and verifies each against the manifest SHA-256 before writing. This was
not hypothetical: on 2026-08-18 the universe builder returned zero symbols
because the bhavcopy files it reads had been pruned, and 74 files had to be
restored to rebuild it. `rank_by_liquidity` now raises rather than silently
ranking on whatever remains locally.

**Cost if wrong.** Low. Worst case a file is kept locally longer than
necessary, which is the safe direction to be wrong in. The dangerous
direction — deleting something not actually in the bucket — is prevented by
the exact-size check, not by trusting that a sync command exited zero.
