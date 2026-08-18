# 005 — Fundamental and earnings data: screener.in vs official sources

**Sprint:** 1 (parallel workstream) · **Date:** 2026-08-18 · **Confidence:**
mixed, stated per source

## Question

What fundamental and earnings-related data should feed analysis, and can it
come from screener.in as requested?

## What actually matters, and why

Ranked by how directly it moves a price and how obtainable it is
point-in-time:

1. **Earnings date and result timing** — the announcement itself is a discrete,
   dated event with real reaction. `filingDate` / `broadCastDate` are exactly
   the `knowledge_time` this project's data layer requires.
2. **Reported vs consensus (surprise)** — same problem flagged in research note
   004 for macro data: no free Indian source publishes analyst consensus, so
   "beat/miss" is not computable from anything found so far. This is a bigger
   gap than the data itself.
3. **Corporate announcements generally** — litigation, board changes, analyst
   meets, cessations. High volume, mixed signal, but genuinely point-in-time
   from the exchange.
4. **Raw financial statement line items** (revenue, profit, margins) — the
   traditional "fundamental data." Needed for value/quality factors, but lowest
   urgency: it changes quarterly and can be sourced later without losing
   anything, unlike the event-timing data above.
5. **Ratios and screens** (P/E, ROE, piotroski-style composites) — this is
   screener.in's actual product: fundamentals *pre-computed and packaged*.
   Convenient, but derivable from (4) once we hold raw statements, so it is not
   uniquely valuable the way NSE's official filing timestamps are.

## screener.in — checked directly, not assumed

**robots.txt** (`screener.in/robots.txt`, fetched 2026-08-18) disallows a few
query-parameter paths and `/user/*`; company pages like `/company/RELIANCE/` are
not blocked.

**Terms of Service** (`screener.in/guides/terms/`, fetched 2026-08-18, read in
full — the terms page is at `/guides/terms/`, not the more obvious
`/terms/`). Verbatim:

> "Permission is granted to use the materials (information or software) on
> Site for **personal, non-commercial transitory viewing only**. This is the
> grant of a license, not a transfer of title, and under this license you may
> not: **modify or copy the materials**; use the materials for any commercial
> purpose... or **transfer the materials to another person or "mirror" the
> materials on any other server**."

And on termination: **"you must destroy any downloaded materials in your
possession."**

**This is more explicit than either NSE's or Trendlyne's clause.** It doesn't
just restrict "automated collection" in the abstract — it names copying and
mirroring specifically, which is precisely what landing a Parquet database does.
Same pattern as ADR-006 and ADR-009, but the clause here leaves less room for
interpretation: storing scraped rows in `data/landing/` is not "transitory
viewing," regardless of whether it is automated or manual, and regardless of
commercial intent (this project isn't commercial, but the clause bars copying
independent of that).

screener.in does reference a **Premium** tier with **export**, which the
homepage mentions but which was not investigated further — a paid, authorised
export is a completely different question from scraping the free site, and
worth checking on its own if screener.in's specific compiled ratios are wanted
later.

## Official alternatives — verified working, historical, and free

### NSE corporate announcements
`nseindia.com/api/corporate-announcements?index=equities` — live feed, 200,
20 rows returned in the test call (`KPIGREEN`, `TALWALKARS`, `GRINFRA` —
litigation, cessation, analyst-meet notices). Real point-in-time announcement
data, not a snapshot.

### NSE financial results — the standout find
`nseindia.com/api/corporates-financial-results?index=equities&period=Quarterly&from_date=...&to_date=...`

**This endpoint genuinely honours its date parameters** — unlike the FII/DII
trap in research note 004's addendum, which silently returned today's data for
any date requested. Verified by requesting two different quarters and getting
two different, correct result sets:

| Request | Rows | Sample |
|---|---|---|
| Current quarter (no date filter) | 3,816 | `broadCastDate: 30-Jul-2026` |
| `from_date=01-01-2020&to_date=31-03-2020` | 3,007 | `fromDate: 01-Oct-2019, toDate: 31-Dec-2019` |

Schema includes `symbol`, `companyName`, `isin`, `financialYear`, `period`,
`consolidated`/`standalone`, `audited` flag, `fromDate`/`toDate` (the reporting
period), and — critically — **`filingDate` and `broadCastDate`**, which are
genuine knowledge-time fields. This single endpoint gives both the earnings
calendar (highest-value item above) and result metadata, official, historical,
and already inside ADR-006's accepted NSE scope.

### BSE announcements
`api.bseindia.com/BseIndiaAPI/api/AnnGetData/w` responded 200 but with `"No
Record Found!"` for the parameters tried — the request shape was not found
correctly. Not pursued further; BSE likely has an equivalent, unconfirmed.

## Recommendation

**Do not scrape screener.in.** Its terms are the clearest anti-copying clause
found in this project so far, and unlike the FII/DII situation there is a
working, historical, official substitute that needs no permission decision:

1. **NSE financial-results endpoint** — backfill the earnings calendar and
   filing metadata. Genuinely historical, genuinely point-in-time, inside
   ADR-006's existing scope. Start here.
2. **NSE corporate announcements** — capture going forward for the same reason
   ticks and FII/DII cash need capturing going forward: it is a live feed with
   no confirmed historical archive.
3. **Raw financial statement line items** — lowest urgency, deferred; can be
   sourced later (via `resultDetailedDataLink` in the results payload, an
   authorised export, or another provider) without losing anything, since
   nothing about it is time-sensitive the way live feeds are.
4. **Consensus/surprise data** — unresolved, same gap as macro research note
   004. May be the binding constraint on earnings-surprise strategies.

## What I could not verify

- Whether `corporates-financial-results` goes back further than 2020 (only
  2020 and current-quarter were tested).
- The correct BSE announcements request shape.
- What screener.in's Premium export actually contains or costs — not
  investigated, since it is a different decision (authorised paid access)
  from the scraping question that was asked.
- Whether `resultDetailedDataLink` in the results payload points to XBRL
  filings with the actual statement line items — the field exists but its
  contents were not fetched.
