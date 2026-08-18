# ADR-011 — Collect fundamentals from screener.in

**Date:** 2026-08-18 · **Sprint:** 1 (fundamentals workstream) · **Status:** accepted
**Decided by:** the operator, explicitly, after being shown the clause below.

**Context.** Fundamental statement data (quarterly results, P&L, balance sheet,
cash flow, ratios, shareholding) is wanted for analysis. screener.in packages
this conveniently per company.

**Options.** (a) NSE's official `corporates-financial-results` endpoint, which
was verified working and genuinely historical (research note 005). (b)
screener.in's Premium tier, which advertises export. (c) Scrape screener.in.

**Choice.** (c). Operator decision, 2026-08-18, after being shown that this is
the most explicit anti-copying clause encountered in this project.

**The clause**, read directly at `screener.in/guides/terms/` (note: not
`/terms/`, which 404s):

> "Permission is granted to use the materials... for **personal,
> non-commercial transitory viewing only**... under this license you may not:
> **modify or copy the materials**... or **transfer the materials to another
> person or 'mirror' the materials on any other server**."

and on termination: **"you must destroy any downloaded materials in your
possession."**

**Why this is recorded rather than folded into ADR-006 or ADR-009.** Each of
those was a distinct decision about a distinct source, and this clause is
stronger than both: it names *copying* and *mirroring* specifically, which is
exactly what writing Parquet to a landing zone does. It is also not conditional
on the use being automated or commercial — manual copying is equally covered.
There is no reading under which this is permitted, and unlike the FII/DII case
there *is* a working official substitute (option a). The operator chose (c)
knowing that.

**Constraints kept**, as with ADR-006 and ADR-009:

1. **2.5s between requests** — deliberately slower than the exchange
   downloaders, because this is a small site rather than an exchange archive.
2. **Stop, do not push.** A 401 or 403 raises `RefusedError` and halts the run
   immediately rather than retrying. Being refused is a signal, not an obstacle.
3. **No evasion.** No IP rotation, no identity cycling, no attempt to defeat
   bot detection.
4. **No redistribution.** Private research on one operator's own capital.

**Snapshots, not overwrites.** Each fetch is stored as its own dated Parquet
file with a `knowledge_time`. Fundamentals are *restated* — a company revises a
prior quarter — so overwriting would silently destroy the ability to ask "what
did we believe this number was in March?", which is the entire point of the
bitemporal discipline in `CLAUDE.md`.

**Cost if wrong.** Access is blocked, and we fall back to option (a), NSE's
official endpoint, which needs no permission decision and is already inside
ADR-006's scope. Anything already collected stays usable; it simply stops
updating. Note the termination clause asks for downloaded materials to be
destroyed — a request this project would be unable to honour selectively once
the data is inside a landing zone, which is worth understanding as part of the
accepted risk.

**Revisit when:** access is blocked, the Premium export is evaluated, or the
NSE endpoint proves sufficient on its own.
