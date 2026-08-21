# ADR-038 — Mutual fund NAVs from AMFI, not Morningstar

**Date:** 2026-08-21 · **Sprint:** fleet scale-up · **Status:** accepted

**Context.** The operator asked to bring in the Morningstar mutual fund data
held in `~/Documents/Trade`. Inspecting that database first: the Morningstar
table holds **6 rows**. The scrape never worked. What is actually there is
2,529 fund records and **1,332,445 NAV rows**, and both came from AMFI —
`NAVAll.txt` for the universe, `api.mfapi.in` for history.

**Options.** (a) Fix and run the Morningstar scraper. (b) Ingest AMFI directly.
(c) Copy the existing SQLite database across.

**Choice.** (b), with mfapi.in for history.

**Why.** AMFI is the industry body that *publishes* the NAV, so it is the
primary source rather than a rendering of one; the file is a plain
pipe-delimited dump meant to be read programmatically; and it covers all 14,288
schemes rather than the six the Morningstar scrape produced. (c) was rejected
because a copied database has no provenance — no `knowledge_time`, no immutable
landing file, nothing to re-derive it from. mfapi.in is a community mirror and
is recorded as such: **where it and AMFI disagree, AMFI wins.**

Morningstar's star and analyst ratings are the one thing AMFI does not publish.
Those six rows were that. If the ratings are wanted, they are a separate source
decision, not a side effect of this one.

**Two things this found.**

*The old URL fails silently.* `www.amfiindia.com/spages/NAVAll.txt` now 302s to
`portal.amfiindia.com`. Fetched without following redirects it returns a short
HTML page, which **parses as zero schemes rather than as an error** — so a
scraper written against it keeps running and ingests nothing. `Trade`'s scraper
is in exactly that state. Our parser raises on an empty result instead.

*`knowledge_time` is the day after the NAV date.* AMFI publishes day D's NAV on
the evening of D. A strategy deciding at the close on D cannot have seen it, so
`knowledge_time = D + 1`. Conservative by up to a day and never optimistic —
the alternative is `HISTORY.md` correction 1 again, one asset class over.

**On the operator's instruction not to weigh terms of service.** Raised once,
answered, and not re-raised. AMFI is the least exposed of the sources here in
any case: it is an official publication in a machine-readable format. The
client identifies itself honestly as `EulerLab/0.1` rather than impersonating
Chrome, which `Trade` does — a browser user-agent is a small lie to a server and
makes our traffic indistinguishable from a person's.

**Cost if wrong.** Low and reversible. The landing zone holds the raw AMFI file
per day, immutably, so any parsing or adjustment decision can be re-derived
without re-fetching. If mfapi.in disappears, the daily snapshots keep
accumulating history from the day the ingest started — which is why the
snapshot runs first and the backfill second.
