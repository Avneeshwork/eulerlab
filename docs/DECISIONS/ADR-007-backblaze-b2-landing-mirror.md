# ADR-007 — Mirror the landing zone to Backblaze B2

**Date:** 2026-08-18 · **Sprint:** 1 · **Status:** accepted
**Amends:** ADR-003, which chose local disk with an external HDD for backup.

**Context.** ADR-003 put the landing zone on local disk, on the reasoning that
what matters is the *schema* — immutability, bitemporal columns, rebuildability
— not the storage engine. That reasoning still holds, but it left the landing
zone as a single copy on one laptop. The landing zone is the one thing in this
project that genuinely cannot be regenerated: it is the record of what the
exchange served on a given day, and losing it means losing history that the
archive may not serve twice. The operator asked for cloud storage.

**Options.** (a) Local only, as ADR-003. (b) Cloudflare R2. (c) Backblaze B2.
(d) AWS S3 in ap-south-1.

**Choice.** (c), Backblaze B2, via its S3-compatible API. Operator decision,
2026-08-18.

**Why.** B2 is the cheapest at rest of the three and the build plan already
named it. Because it speaks S3, the implementation is provider-agnostic —
switching to R2, S3 or Wasabi is one `endpoint_url` in `config/storage.yaml`,
so this choice is close to free to reverse.

**Mirror, not primary.** Local disk stays the working copy and the download
target; B2 is a verified second copy written by `make sync-cloud` after the
fact. Writing every file straight to the cloud during a multi-hour backfill
would add a network failure mode to each of ~5,800 downloads for no benefit.
The sync is independently resumable and skips whatever is already present.

**Integrity is checked with our own SHA-256, not the ETag.** S3's ETag is an
MD5 for simple uploads and something else for multipart ones, so it is not a
dependable equality check across providers. Every object carries its SHA-256 in
user metadata, compared against the manifest. An object already present with a
*different* hash is reported and never overwritten — that situation means
something unexpected happened, and destroying the evidence would be the worst
possible response.

**Cost line** (required by `CLAUDE.md`): **B2 at roughly $6/TB/month.** The
bhavcopy history is single-digit GB, so this is a few rupees a month — call it
under ₹100. It replaces "one copy on one laptop". No measurement demanded it;
the justification is that the landing zone is irreplaceable, which is the same
argument as the options recorder. It also adds **`boto3`** as a dependency —
heavier than this project's usual bar, but hand-rolling SigV4 request signing
would be worse in every way that matters.

**Cost if wrong.** Very low. The mirror is additive: nothing depends on it, and
deleting the bucket loses nothing that is not still on disk.
