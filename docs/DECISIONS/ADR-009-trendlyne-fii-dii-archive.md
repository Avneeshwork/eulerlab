# ADR-009 — Collect historical FII/DII cash flows from Trendlyne

**Date:** 2026-08-18 · **Sprint:** 1 (macro workstream) · **Status:** accepted
**Decided by:** the operator, explicitly, after being shown the clause below and
told this is not covered by ADR-006.

**Context.** NSE publishes no archive of daily FII/DII cash flows. Its
`fiidiiTradeReact` endpoint serves the latest day only, and — worse — accepts a
`?date=` parameter that it silently ignores, returning today's numbers with a
200 for any date requested. Of the aggregators that do keep an archive,
Trendlyne is the deepest, referencing years back to 2011.

**Options.** (a) Skip it; use NSE participant-wise OI instead, which is
official, historical and already in scope. (b) Ask Trendlyne for written
authorisation. (c) Collect from Trendlyne anyway. (d) Find BSE's official
endpoint.

**Choice.** (c). Operator decision, 2026-08-18. (a) is proceeding in parallel
regardless, as it needs no permission.

**Why this is a separate ADR and not covered by ADR-006.** ADR-006 accepted the
risk of collecting NSE's own public market record against a general
anti-scraping clause. This is a different kind of claim. Trendlyne's terms, read
directly at `trendlyne.com/terms/` on 2026-08-18, say:

> "You may not resell, redistribute, broadcast or transfer the information **or
> use the information in a searchable, machine-readable database** unless
> separately and specifically authorized in writing by trendlyne.com prior to
> such use."

That names our exact intended use. And the archive is Trendlyne's own product —
the underlying numbers are public exchange data, but the compilation is the
thing they built and sell. Reading ADR-006 as covering this would have been
stretching a decision about public records to cover a commercial dataset, so it
was put to the operator separately and answered.

**Constraints kept**, as with ADR-006:

1. Rate limited, single-threaded, and it stops rather than pushes if refused.
2. No evasion: no IP rotation, no identity cycling, no attempt to defeat bot
   detection.
3. **No redistribution.** Their clause bars both redistribution and
   machine-readable database use; we breach the second and not the first, which
   does not make it permitted but does keep the footprint to private research on
   one operator's own capital.
4. Their `robots.txt` does not block these paths — noted, and explicitly *not*
   treated as permission. That was the exact mistake NSE nearly taught us.

**Cost if wrong.** Access is blocked, and we fall back to (a), which is running
anyway and is arguably the better dataset. Nothing downstream depends on this
being available, and nothing built on it would need to be discarded — the data
would simply stop updating.

**Revisit when:** written authorisation is obtained or refused, BSE's official
endpoint is found, or access is blocked.
