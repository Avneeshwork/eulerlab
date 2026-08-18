# 002 — Where do 11 years of NSE end-of-day data come from, and can Zerodha serve it?

**Sprint:** 1 · **Date:** 2026-08-18 · **Confidence:** high (every URL below was
fetched, not inferred from search results)

## Question

The operator's data-source policy is: Zerodha primary wherever it can serve the
need, one fallback, no third source. Sprint 1 needs equity and F&O end-of-day
history from 2015-01-01. **Can Kite Connect provide it?** If not, what exactly
is the fallback and what are its file formats?

## Sources

| Source | URL | Fetched | Type |
|---|---|---|---|
| Kite historical API | https://kite.trade/docs/connect/v3/historical/ | 2026-08-18 | Broker API docs (primary) |
| Kite rate limits | https://kite.trade/docs/connect/v3/exceptions/ | 2026-08-18 | Broker API docs (primary) |
| Kite instruments list | https://kite.trade/docs/connect/v3/market-quotes/ | 2026-08-18 | Broker API docs (primary) |
| Kite Connect pricing | https://zerodha.com/products/api/ | 2026-08-18 | Vendor pricing page (primary) |
| NSE UDiFF equity bhavcopy | https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip | 2026-08-18 | Exchange archive (primary) |
| NSE UDiFF F&O bhavcopy | https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip | 2026-08-18 | Exchange archive (primary) |
| NSE legacy equity bhavcopy | https://nsearchives.nseindia.com/content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip | 2026-08-18 | Exchange archive (primary) |
| NSE legacy F&O bhavcopy | https://nsearchives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip | 2026-08-18 | Exchange archive (primary) |

## Findings

### Kite Connect — cost is fine, structure is not

1. **₹500/month includes historical candle data.** Verbatim from the pricing
   page: *"Full suite of APIs with realtime WebSocket streaming and historical
   candle data for ₹ 500 / month"*. There is **no separate historical add-on
   fee**. This confirms the cost line in ADR-004 — good news, and one fewer
   assumption.
2. **Rate limits:** historical candles **3 req/sec**, quotes **1 req/sec**,
   everything else 10 req/sec.
3. **Historical data is per-instrument**, not per-market-day:
   `GET /instruments/historical/:instrument_token/:interval`. A bhavcopy is one
   file containing the entire market for one day. These are different shapes of
   the same information, and the difference decides this sprint.
4. **Expired contracts are only partly reachable.** The docs describe
   `continuous=1` as returning day candles for expired contracts of
   *"NFO and MCX **futures** contracts"*. Options are not mentioned. Eleven
   years of Indian derivatives history is overwhelmingly expired **option**
   strikes.
5. **The instruments dump is a current snapshot.** *"The dump is generated once
   everyday"*, and it lists tradable instruments. It is not a point-in-time
   record of what was listed in 2015.
6. **Instrument tokens are reused.** Verbatim: *"Exchanges may reuse instrument
   tokens for different derivative instruments after each expiry."* A token is
   therefore unsafe as a historical join key — which is exactly why `CLAUDE.md`
   requires internal IDs.

**The disqualifying point is 5, not 4 or the cost.** Driving a historical
backfill from a list of instruments that exist *today* reproduces survivorship
bias precisely: every delisted company and every expired contract is silently
absent, and the resulting history contains only the survivors. That is the
single failure mode this platform is being built to prevent, and no amount of
care in the downloader can undo it.

### NSE archives — two formats, one changeover

Both were downloaded and their contents inspected.

**Current "UDiFF" format** — 34 columns:
```
TradDt, BizDt, Sgmt, Src, FinInstrmTp, FinInstrmId, ISIN, TckrSymb, SctySrs,
XpryDt, FininstrmActlXpryDt, StrkPric, OptnTp, FinInstrmNm, OpnPric, HghPric,
LwPric, ClsPric, LastPric, PrvsClsgPric, UndrlygPric, SttlmPric, OpnIntrst,
ChngInOpnIntrst, TtlTradgVol, TtlTrfVal, TtlNbOfTxsExctd, SsnId, NewBrdLotQty,
Rmks, Rsvd1..4
```
Equity file for 2026-08-14: 3,464 rows, 189 KB zipped. One schema now covers
both cash and derivatives. Note it carries `ISIN`, both `TradDt` and `BizDt`,
and `NewBrdLotQty` — a *time-stamped lot size*, which is directly what the
Sprint 3 security master needs.

**Legacy format** — different, and thinner:
```
equity : SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY,
         TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN          (13 cols)
F&O    : INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP, OPEN, HIGH, LOW,
         CLOSE, SETTLE_PR, CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI, TIMESTAMP
                                                           (15 cols)
```
2015-01-02: equity 1,605 rows / 58 KB, F&O 28,984 rows / 315 KB. **No lot size
and no ISIN in the F&O file** — both must come from elsewhere for the pre-2024
period.

**Availability, probed directly:**

| Date probed | UDiFF | Legacy |
|---|---|---|
| 2026-08-14 | 200 | 404 |
| 2025-01-02 | — | 404 |
| 2024-12-02 / 2024-11-01 / 2024-09-02 | — | 404 |
| 2024-07-08 | 200 | — |
| 2024-06-03 | — | 200 |
| 2024-01-02 | 200 | — |
| 2023-01-02 / 2022-01-03 / 2020-01-02 / 2015-01-02 | 404 | 200 (2015 confirmed) |

So: **legacy runs to somewhere between 2024-06-03 and 2024-09-02; UDiFF is
backfilled to at least 2024-01-02.** That leaves an **overlap window of roughly
January to July 2024 where both formats exist for the same trading days** —
which is free, exact validation of the mapping between the two schemas. Any
downloader that spans 2015–2026 must handle both, so the overlap is worth
exploiting rather than skipping.

### One engineering trap worth writing down

**`HEAD` requests are unreliable on the legacy path.** Every legacy URL returned
403 or 503 to `HEAD`, including with a browser User-Agent and a session cookie —
and returned `206`/`200` to an ordinary `GET`. The UDiFF path answers `HEAD`
correctly.

The obvious way to check "does this file exist before downloading it" is a HEAD
request, and on this archive it would report ~2,300 trading days as missing when
they are all present. **The downloader must never use HEAD to test existence.**
This is the sort of thing that produces a confident, wrong "missing-day report".

## Decision

**Proposed, pending operator confirmation** (this partly contradicts the stated
"Zerodha first" preference, so it is not being taken unilaterally):

| Data | Primary | Fallback |
|---|---|---|
| Historical EOD (equity + F&O, 2015→) | **NSE archives** | Kite historical API, recent dates only |
| Live / intraday / option chains (Sprint 2+) | **Kite Connect** | NSE (not viable for live) |

Still two sources, per the policy. Kite remains primary for everything it can
actually serve; it is displaced only for historical backfill, and only because
its instrument list is a present-tense snapshot.

## What I could not verify

- **Whether a session cookie is required for the legacy archive.** All
  successful legacy `GET`s were made with a cookie jar present from an earlier
  visit to `nseindia.com`. I did not isolate the variable, so "cookie required"
  is untested either way. The downloader should establish a session anyway and
  we will learn from the first full run.
- **The exact legacy cutover date.** Narrowed to between 2024-06-03 and
  2024-09-02. Search results attribute it to NSE Circular 62424 (12 June 2024)
  with effect from 8 July 2024; **I did not fetch that circular**, so the date is
  hearsay and the code must not hardcode it — probe and fall back instead.
- **Whether Kite serves expired option contracts.** The docs mention futures
  only. Absence of a statement is not proof of absence, but it is enough to
  disqualify Kite for this sprint on point 5 regardless.
- **NSE's trading-holiday list.** Not researched yet. Needed to tell "market
  holiday" from "download failed", and unresolved as of this note.
- **NSE's terms on automated archive access.** Not reviewed. Worth reading
  before running an 11-year backfill.

## Open questions

1. Confirm the source split in the Decision table above. → operator
2. Where does the trading calendar come from? Deriving holidays from "no file
   present" is circular and would mask real download failures.

---

## Addendum, 2026-08-18 — NSE's terms prohibit the backfill

Added after the downloader was built and tested. This is the finding that
decides the sprint, so it belongs in the same note rather than a new one.

**Source:** https://www.nseindia.com/static/nse-terms-of-use — fetched
2026-08-18, page read directly (311 KB), not summarised from search results.

**Verbatim:**

> "User is granted a non-exclusive, non-transferable, limited right to access
> the Website / Mobile Application and avail the services provided by NSE
> through the Website / Mobile Application. User is prohibited to conduct any
> **systematic or automated data collection activities (including scraping,
> data mining, data extraction and data harvesting)** on or in relation to our
> Website / Mobile Application."

**robots.txt says the opposite, and loses.** `www.nseindia.com/robots.txt`
(fetched 2026-08-18) is `User-agent: * / Allow: / / Disallow: /market-data-test`,
and `nsearchives.nseindia.com` serves no robots.txt at all. A permissive
robots.txt is a crawler convention, not a licence; the written Terms of Use
govern, and they are explicit. Anyone reading only robots.txt would conclude
the opposite of the truth — which is why this needed reading rather than
assuming.

**What this means.** A 2015→2026 backfill is roughly 5,600 requests, executed
on a schedule, for the purpose of assembling a dataset. That is a systematic
automated data collection activity by any reading. **The backfill is not run.**
Sprint 1's downloader is complete and tested but deliberately not pointed at
the full range.

**Not a workaround.** Slowing the rate, spreading it over weeks, or rotating
identity would each make the activity harder to notice without making it
permitted. The prohibition is on the activity, not on its speed.

**The sanctioned route exists.** NSE Data & Analytics Ltd operates a historical
data portal (`dotexdata.nseindia.com`) with its own terms and a licence. That —
or written permission from NSE — is what makes bulk historical access
legitimate. Not investigated further: it is a commercial decision for the
operator, not a technical one.

**Already downloaded during development:** 142 files, 31 MB, covering parts of
Jan–May 2015 and one week of Aug 2026, 2.24 M rows. The operator sanctioned
testing "on a handful of days"; this overran that, because two interrupt tests
failed to interrupt (SIGINT is not delivered to background processes in the
build sandbox) and each ran a full month to completion instead of stopping
after seconds. Stated plainly rather than rounded down. No further fetching has
occurred since the terms were read.
