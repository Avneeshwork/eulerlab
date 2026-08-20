# ADR-030 — Reconciliation corrects the record, never the market

**Context.** When our position book and the broker's disagree, something has
to give. `CLAUDE.md` says the broker is the source of truth and local state is
a cache.

**Options.** (a) Correct the local record to match the broker. (b) Place
orders to make the broker match our belief. (c) Correct locally and flag
anything that would need a trade.

**Choice.** (c), and there is no flag that enables (b). `reconcile()` returns
a report and writes nothing; a human decides whether any trade follows.

**Why.** A break means we do not know what happened, and the most common cause
is a fill we failed to record. Trading the difference in that case *doubles*
the position, at exactly the moment we are least able to tell. Auto-correcting
toward our own belief also inverts the source-of-truth rule the moment it
matters most.

**Cost if wrong.** A genuine position break sits open until someone looks at
it. Mitigated by `make reconcile-book` exiting non-zero so it can be
scheduled, and by the kill switch's limits stopping new orders while the book
is in doubt.
