# ADR-039 — Morningstar ratings are landed whole and joined only by name

**Date:** 2026-08-21 · **Sprint:** fleet scale-up · **Status:** accepted

**Context.** ADR-038 chose AMFI over Morningstar for NAVs and noted that star
and analyst ratings were the one thing Morningstar had which AMFI does not
publish. The operator asked for them. `featured-reports.aspx` holds **5,741
funds** — the previous scraper in `~/Documents/Trade` retrieved **6**.

**The problem.** The page carries a Morningstar fund id (`f00000pdux`), a fund
name, and the ratings. **It carries no ISIN and no AMFI scheme code.**
`CLAUDE.md` is unambiguous: *instrument joins use internal IDs only. Never a
ticker, tradingsymbol, or broker token.* A fund name is exactly the kind of
identifier that rule exists to forbid, and it is the only bridge on offer.

**Options.** (a) Join on the name and treat the result as fact. (b) Skip
Morningstar entirely, since it cannot be joined lawfully under our own rules.
(c) Land the ratings whole, keyed by Morningstar's id, and treat the name join
as a separate, labelled, reported approximation.

**Choice.** (c).

**Why.** (a) is the failure this project has already paid for once: joining
corporate actions on a raw ISIN string lost 21.9% of matches silently, and a
rating attached to the wrong fund is the same class of error with none of the
visibility. (b) throws away real data because of a join problem, which is the
wrong end to solve it from — the ratings are perfectly good on their own terms.

So the ratings are a complete, independent dataset keyed on
`morningstar_id`. `join_to_amfi` is a separate function that returns its match
rate, and **a name folding to more than one scheme is left unjoined rather than
resolved by picking one.** `make morningstar` prints the three counts —
matched, ambiguous, unmatched — on every run, so the compromise cannot settle
into the background as though it were solved.

**Two bugs this found, both by running it rather than reading it.**

*The pager was clicked by a fixed control id.*
`...pagerQualitativeRatings$ctl02$ctl01` is the literal **"2"** link, not
"next". Clicking it repeatedly re-served page 2 and the crawl stopped at 400 of
5,741 rows — with the guard reporting a clean stop, which is how it would have
been believed. The target is now found by its label on each page.

*An unrated fund was stored as zero stars.* Morningstar's scale is 1–5; the
page renders unrated as `Star Rating 0`. Storing that as `0` makes "nobody
rated this" indistinguishable from "rated worst", and **405 funds** were
affected. Now `None`. This is the third time in one session that a null has
tried to render as a zero — the fleet list, a backtest with no fills, and now
this — which suggests it is worth treating as a standing hazard rather than
three coincidences.

**Cost if wrong.** Low for the ratings themselves, which stand alone. The join
is where the risk sits, and it is bounded by being advisory: nothing in the
backtest path consumes it, and every row it produces is labelled fuzzy. If a
scheme-code mapping ever becomes available, the landed data does not change —
only the join improves.
