# 004 — What macro data moves the Indian market, and where to get it

**Sprint:** 1 (parallel workstream) · **Date:** 2026-08-18 · **Confidence:** mixed,
stated per source

## Question

Which India-specific macro and flow data actually affects equity prices, and
which sources can we obtain it from reliably and legitimately? Requested as a
new workstream: FPI flows, CPI, WPI, policy announcements and similar.

## The finding that shapes everything else

**A macro series needs two dates, not one, and almost every free source gives
only one.**

CPI for August is *released* in mid-September. A backtest that places August's
CPI on an August date is using information nobody had — textbook lookahead, and
it will manufacture alpha out of nothing. So every series must carry:

* `reference_period` — the month or quarter the number describes
* `release_time` — when it was first published, i.e. our `knowledge_time`
* and separately, the **revision** history, because GDP and IIP are revised

This is the bitemporal rule from `CLAUDE.md` applied to macro, and it is the
reason a "good database" of Indian macro data is mostly a *release-calendar*
problem rather than a scraping problem. Nearly every convenient source
(World Bank, most dashboards) publishes only the latest revised value against
the reference period, which is exactly the shape that leaks the future.

**Practical consequence:** for anything we cannot get with a genuine release
timestamp, the honest options are to record it going forward from today (as with
tick data), or to treat it as unusable for backtesting and only for context.

## Sources checked, 2026-08-18

Every status below came from an actual request, not from documentation.

### Verified working and immediately useful

| Source | URL | Frequency | Depth | Status |
|---|---|---|---|---|
| **NSE participant-wise F&O OI** | `nsearchives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv` | daily | **back to at least 2020-04-01** | 200, schema read |
| **NSE FII/DII cash flows** | `nseindia.com/api/fiidiiTradeReact` | daily | **latest day only** | 200, data read |
| RBI statistics portal | `data.rbi.org.in/DBIE`, `rbi.org.in/Scripts/Statistics.aspx` | varies | long | 200, contents not yet parsed |
| RBI press releases (MPC) | `rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx` | event | long | 200 |
| NSDL FPI reports | `fpi.nsdl.co.in/web/Reports/Latest.aspx` | fortnightly + daily | long | 200, not yet parsed |
| World Bank API | `api.worldbank.org/v2/country/IND/indicator/...` | **annual only** | 1960– | 200, JSON verified |

**The participant-wise OI file is the standout.** Its schema splits open
interest by *who holds it* — Client, DII, FII, Pro — across index futures, stock
futures, and index and stock options, long and short separately. Example row
from 2026-08-14:

```
Client Type, Future Index Long, Future Index Short, ..., Total Long, Total Short
Client,      211638,            55956,              ..., 13152111,   9490438
DII,         50830,             20040,              ..., 479918,     4794479
```

That is genuine positioning data, daily, free, and historically downloadable.
Of everything surveyed it is the most immediately valuable, because positioning
is a *cause* of price movement rather than a lagging summary of it.

### The FII/DII cash-flow gap

`fiidiiTradeReact` returns **only the most recent day**. There is no historical
range parameter. So daily FII/DII cash flow is, like tick data, only available
if someone was capturing it. Today it returned:

```
DII      buy 16654.08  sell 11552.62  net  +5101.46   (17-Aug-2026)
FII/FPI  buy 11546.16  sell 14081.26  net  -2535.10
```

**This is the third dataset in this project with that property** (option chains,
ticks, now FII/DII cash). The pattern is worth naming: anything published as a
*current state* rather than an *archive* is unrecoverable, and a one-line daily
job started today is worth more than any amount of planning later.

### Not yet verified

| Source | What it has | Why not verified |
|---|---|---|
| MoSPI (`cpi.mospi.gov.in`) | CPI, IIP, GDP | Connection failed on first attempt; the main `mospi.gov.in` responds. Needs a proper look for a bulk file or API |
| Office of Economic Adviser (`eaindustry.nic.in`) | WPI | Page responded but returned 1 KB, so the data sits behind a form or frame. No direct spreadsheet link found |
| IMF DataMapper | forecasts | 403 |
| FRED | some India series | Needs a free API key, which the operator would have to create |

## What actually moves the Indian market, ranked by usefulness to us

Ranked by frequency × whether it is a genuine surprise × whether we can get it
point-in-time. High-frequency positioning beats low-frequency macro, because a
monthly number that everyone forecasts is mostly priced before release.

1. **Participant-wise OI (FII/DII/Pro/Client)** — daily, free, historical.
   Positioning extremes precede reversals. Start here.
2. **FII/DII cash flows** — daily, but capture-only from today.
3. **RBI MPC decisions and repo rate** — event-driven, and the *surprise versus
   consensus* is what matters, not the level. Consensus is the hard part to
   source.
4. **CPI, WPI** — monthly. Release dates are published in advance, so the
   release calendar is obtainable even where the history is awkward.
5. **IIP, GDP** — monthly/quarterly, heavily revised. Revisions make these
   dangerous without proper vintages.
6. **Union Budget** — annual, single largest scheduled volatility event.
7. **Crude oil, USDINR, DXY** — daily, and India is a large oil importer, so
   these are arguably more predictive than most domestic prints.
8. **Corporate results calendar** — event-driven, per instrument. Needs the
   security master first, so it waits for Sprint 3.

## Terms of use

Checked: none of `mospi.gov.in`, `eaindustry.nic.in`, `nsdl.co.in` or
`rbi.org.in` serves a real `robots.txt` — all returned HTML error pages, so no
crawl directives exist either way.

**NSE sources inherit ADR-006.** NSE's Terms of Use prohibit systematic
automated collection; the operator was shown this and decided to proceed. The
participant-OI and FII/DII endpoints above are NSE, so the same accepted risk
applies, unchanged.

RBI, MoSPI and NSDL terms have **not** been read. They should be before any
bulk collection from those hosts, and I have not done it.

## Recommendation

Three steps, cheapest and most valuable first:

1. **Backfill participant-wise OI** from 2020 to today. Daily CSVs, ~1,600
   files, the same downloader pattern already built and proven. Highest value
   per hour of work by a wide margin.
2. **Start a daily capture job for FII/DII cash flow.** One request per day.
   Trivial to build, and every day skipped is permanently lost.
3. **Then** tackle CPI/WPI/IIP properly, with release dates rather than only
   reference periods — accepting that this is the fiddly one and that a series
   without a release timestamp is context, not a backtest input.

## What I could not verify

- Whether participant-OI files exist before April 2020 (three dates in 2020,
  2022 and 2024 all returned 200; earlier not probed).
- Whether NSE publishes an archive of historical FII/DII cash flows anywhere
  other than the current-day API. I looked at the obvious endpoint only.
- Any MoSPI or eaindustry bulk-download path. Both need real work.
- Consensus/forecast data for any Indian indicator. Without it, "surprise" is
  not computable, and surprise is what moves prices. This may be the binding
  constraint on macro-event strategies and is worth settling early.

---

## Addendum, 2026-08-18 — third-party FII/DII sources

Checked at the operator's request: StockEdge, 5paisa, Moneycontrol, Trendlyne,
Groww, Chartink, BSE.

### A trap in NSE's own endpoint, worth more than any of them

`nseindia.com/api/fiidiiTradeReact` **accepts a `?date=` parameter and silently
ignores it.** Asked for 14-08-2026, 10-07-2026 and 15-01-2024, it returned
17-Aug-2026 data every time — HTTP 200, valid JSON, correct schema, wrong day.

A naive backfill looping over five years of dates would write ~1,250 files that
all contain the same day's numbers, with no error raised anywhere and every file
passing a schema check. **Any date-parameterised endpoint must be tested by
comparing the returned date against the requested one** before it is trusted;
status codes and schema validity prove nothing here.

This also settles it: NSE publishes no historical FII/DII cash archive.

### What the third parties actually have

| Platform | Finding |
|---|---|
| **Trendlyne** | Deepest archive — page references years back to **2011**, server-rendered rather than JS |
| **Groww** | ~31 days, in a clean `__NEXT_DATA__` JSON payload |
| **StockEdge** | A JavaScript app; raw HTML has no data. Three guessed API paths all 404 |
| **Moneycontrol** | 301 redirect; not pursued |
| **5paisa** | 404 on the FII/DII path |
| **BSE** | Three guessed API endpoints all 302 to an error page. BSE does publish this data; the right path was not found |

### Terms: this is a different question from ADR-006

`robots.txt` on Trendlyne, Groww and StockEdge blocks only specific bots or
unrelated paths — none blanket-disallows. **That is not permission**, which is
exactly the lesson from NSE, where robots.txt said `Allow: /` while the Terms of
Use prohibited automated collection.

Trendlyne's terms, read directly at `trendlyne.com/terms/` on 2026-08-18:

> "You may not resell, redistribute, broadcast or transfer the information **or
> use the information in a searchable, machine-readable database** unless
> separately and specifically authorized in writing by trendlyne.com prior to
> such use."

**This is a stronger and more specific prohibition than NSE's, and it is a
different kind of case.** NSE's FII/DII numbers are a public market record that
NSE itself publishes; ADR-006 accepted the risk of collecting public data
against a general anti-scraping clause. Trendlyne's *archive* of those numbers
is the product they built and sell, and their clause names our exact intended
use — putting it in a machine-readable database.

ADR-006 should not be read as covering this. It is a separate decision, and it
has not been taken.

Worth noting the clause itself contemplates permission: "unless separately and
specifically authorized in writing". For a single-operator research use, asking
costs an email.

### Clean routes that need no new decision

1. **NSE participant-wise F&O OI** — daily, historical to at least 2020,
   official, and already inside ADR-006's accepted scope. Richer than cash
   FII/DII anyway: it splits positioning by FII/DII/Pro/Client across futures
   and options, long and short.
2. **Daily capture of FII/DII cash from NSE going forward** — one request per
   day, the same thing a person visiting the page does.
3. **BSE** — an official second source. The endpoint needs finding, which is
   work rather than a decision.
