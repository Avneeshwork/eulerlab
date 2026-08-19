# ADR-014 — `as_of` is a required argument, not a convention

**Date:** 2026-08-19 · **Sprint:** 4 · **Status:** accepted

**Context.** `CLAUDE.md` requires that the research read API be *structurally
incapable* of returning `knowledge_time > as_of`. Every dataset already stores
both timestamps, so the remaining question is where the rule is enforced. The
tempting shape is a store that filters when you ask it to. That is the shape
that leaks: the one call site that forgets is silent, and a lookahead leak is
silent in the direction you already want to believe.

**Options.** (a) `as_of: datetime | None = None`, filter when supplied.
(b) Required but positional. (c) Required and keyword-only, with no public
reader that omits it.

**Choice.** (c), plus `Record` frozen and both timestamps required tz-aware.

**Why.** (a) makes the correct call the longer one, which loses eventually —
and it fails open, returning *more* data when misused rather than erroring.
(b) is safe against omission but not against the wrong slot: `query(key, as_of)`
and `query(as_of, key)` both typecheck under a loose signature. (c) cannot be
called wrong: the argument cannot be dropped, cannot be passed in the wrong
position, and there is no unfiltered public method to reach past. `Record` is
frozen so a filtered record cannot have its `knowledge_time` rewritten and
smuggled back in, and tz-awareness is enforced because 15:30 IST and 15:30 UTC
are five and a half hours apart — one of them is after the close.

**Cost if wrong.** Low and local. Callers pass one extra keyword. If a genuine
"all vintages" reader is ever needed, it is a new explicitly-named method
(`audit_unknowable` already does this for tests), not a default that weakens
every existing call site.
