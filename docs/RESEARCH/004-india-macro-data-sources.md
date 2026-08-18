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
