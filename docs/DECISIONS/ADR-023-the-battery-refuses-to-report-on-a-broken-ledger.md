# ADR-023 — The battery verifies the ledger before it reports anything

**Date:** 2026-08-19 · **Sprint:** 13 · **Status:** accepted

**Context.** Every statistic in the overfitting battery divides by the number
of things ever tried. Deflated Sharpe, minimum backtest length and the whole
multiple-testing correction all get **more favourable as that count falls**.
So the one number the battery rests on is also the number with the strongest
possible incentive to shrink, and Sprint 8's log was append-only by
convention: plain JSONL on a disk anyone can write to.

The realistic tamper is not adding a fake row. It is quietly deleting a few
real ones.

**Options.** (a) Trust the append-only convention. (b) Make the file
read-only. (c) Hash-chain each entry to its predecessor and verify before
reporting.

**Choice.** (c), and the battery **refuses to print any result** when the
chain is broken.

**Why.** (a) is not a control, it is a promise. (b) is trivially reversible
and gives false assurance. (c) does not make tampering impossible — anyone can
rewrite the whole chain — but it makes it **detectable and deliberate** rather
than quiet, which is the difference between an accident and a decision.

Refusing to report matters as much as detecting. A battery that printed
"PBO 20%, chain broken" would have its headline read and its warning ignored,
and the numbers would be wrong in the flattering direction. There is no
partial credit available here: if the denominator is unverifiable, every
number above it is meaningless.

One honesty limit is recorded in the tests rather than hidden: **truncating
the tail of the chain leaves every remaining link valid.** The hash chain
proves that what remains has not been altered; it cannot prove that nothing
was removed from the end. Sequence numbering catches gaps in the middle, and
nothing catches a clean truncation. That is a real limit and saying so is
better than implying a guarantee the design does not provide.

Sprint 8's unchained trials are **migrated in**, marked `migrated: true`,
rather than discarded. Those evaluations really happened, and dropping them
would understate the count in exactly the flattering direction the ledger
exists to prevent — but the chain can only attest to what it has held since,
and claiming otherwise would be the same dishonesty one layer up.

**Cost if wrong.** Low. Verification is a single pass over a small file. The
failure mode is a false alarm after an unrelated refactor, which is why the
hash covers a canonically-ordered payload rather than raw file bytes.
