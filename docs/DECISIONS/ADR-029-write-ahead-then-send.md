# ADR-029 — The intent is fsynced before the network call

**Context.** If the process dies mid-order, recovery can only work from what
is on disk. The ordering of "record" and "send" decides what is recoverable.

**Options.** (a) Send, then record what happened. (b) Record the intent,
fsync, then send, then record the outcome. (c) Record in memory and flush
periodically.

**Choice.** (b). `OMS.submit` journals a `CREATED`/`INTENT` event, fsynced,
before the adapter is touched. The outcome is a second event.

**Why.** With (a), a crash between the send and the record leaves an order at
the exchange that no local record mentions — and reconciliation cannot find it,
because reconciliation compares against a list that does not contain it. That
is the one failure mode with no recovery path at all. With (c) the same hole
exists, just smaller. The chaos scenario `killed after the send` is this
decision as an executable test: a subprocess is `SIGKILL`ed between the two,
and a fresh process finds the live order and adopts it.

**Cost if wrong.** An fsync per order event. At five orders per second that is
irrelevant; if this ever becomes a throughput problem it will be because the
system is doing something it was explicitly built not to do.
