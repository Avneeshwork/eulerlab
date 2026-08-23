# 023 — Which news source covers India, US, crypto and FX

**Question.** The platform trades NSE equities, US equities, crypto and FX. Is
there one news provider that covers all four? What does it cost?

**All figures below were measured on 2026-08-23**, not read off a feature
table. Every source was fetched; the counts are what came back.

## The short answer

No commercial vendor covers all four. The two that plausibly could — FMP and
EODHD — put **India behind a paywall and will not let you verify it before
paying**. Meanwhile a free, keyless source covers all four per-instrument and
survives universe-scale polling.

## Measured: free, no signup

| Source | India | US | Crypto | FX | Per-symbol | Measured |
|---|:--:|:--:|:--:|:--:|:--:|---|
| **Google News RSS** | ✅ | ✅ | ✅ | ✅ | ✅ | 100 items/query, all classes |
| **NSE announcements** | ✅ | — | — | — | ✅ | 20 filings, PDFs + timestamps |
| **SEC EDGAR** | — | ✅ | — | — | ✅ | 1,001 filings for AAPL |
| ET / Mint / Business Standard / Hindu BL | ✅ | — | — | — | ✗ | 35–60 items each |
| ForexLive / FXStreet | — | — | — | ✅ | ✗ | 25–30 items |
| CoinDesk / Cointelegraph | — | — | ✅ | — | ✗ | 25–30 items |
| Moneycontrol | ✅ | — | — | — | ✗ | 4–15 items (thin) |
| Nasdaq RSS | — | ✅ | — | — | ✗ | 15 items |

### Google News RSS is the only universal layer

```
https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en
```

100 items for every instrument tried, across all four asset classes — Indian
large-, mid- and small-caps (Reliance, Tega, Kaynes), US equities, BTC and SOL,
EURUSD and USDINR. Each item carries `pubDate`, `source` and a stable `guid`,
so deduplication is solved.

**Scale test, which is what decides usability:** 20 NSE symbols at 6 workers
completed in **5.9 seconds, 20/20 succeeded**, averaging 98 items each, slowest
request 2.56s. No throttling appeared. A Nifty-50 sweep is well under a minute.

### The exchange feeds are the authoritative layer

Google News tells you what was *written*. These tell you what was *filed* —
which is the ground truth behind most single-stock moves.

**NSE** (`/api/corporate-announcements?index=equities`) returns structured
filings with timestamps and PDF links. It needs a cookie bootstrap: fetch the
corporate-filings page first, carry the jar, and send a `Referer`. Without that
it returns an empty list rather than an error, which is a silent failure worth
guarding against.

**SEC** (`data.sec.gov/submissions/CIK{n}.json`) returned 1,001 recent filings
for Apple, keyless. The full-text search at `efts.sec.gov` also answers, across
all companies. The **old** `browse-edgar` atom feed returned 0 entries — it
looks retired, so anything built on it should move.

## Measured: commercial

| Vendor | Free tier | India | Verdict |
|---|---|---|---|
| **FMP** | 250 calls/day, EOD | Unknown; US starts at paid tier | News is **paid** Starter $22/mo (see 022) |
| **EODHD** | 20 calls/day | **`RELIANCE.NSE` → 403** | Demo serves US/FX/crypto only |
| Marketaux | — | — | Pricing page 403s; unverified |
| Finnhub | — | — | Docs do not state India coverage |
| CryptoCompare | — | — | Now 401s; key required |
| Yahoo Finance RSS | — | — | **429 on every attempt**; treat as gone |

EODHD is the sharpest illustration: its demo key happily served `AAPL.US`,
`EURUSD.FOREX` and `BTC-USD.CC`, then returned **403 Forbidden** for
`RELIANCE.NSE` and for the exchange list that would have settled the question.
You cannot confirm India coverage without buying first.

## What could not be determined

- **Whether FMP or EODHD actually cover NSE well.** Both gate it behind
  payment, and neither exposes a symbol list to a free key. Unresolved, and
  not resolvable without spending money.
- **Marketaux and Finnhub India coverage.** Marketaux's pricing page 403s to a
  scripted fetch; Finnhub's docs page did not state it.
- **Google News RSS rate limits at 100+ symbols.** Verified clean to 20
  symbols / 6 workers. The ceiling above that is untested, and Google
  publishes no limit for this endpoint.
- **Historical depth for Google News RSS.** It is a recent-items feed. Like the
  ForexFactory calendar (021), history must be accumulated forward — it cannot
  backfill.

## Recommendation

A composite of free sources, which is also the only option that covers all four
markets:

1. **Google News RSS** — universal per-instrument layer, all four asset classes
2. **NSE announcements** — authoritative India corporate events
3. **SEC EDGAR** — authoritative US corporate events
4. **ForexFactory** — macro calendar, already built (021)
5. **Sector RSS** (FXStreet, CoinDesk, ET) — market-wide context

No paid vendor until something measured is missing. Per the cost rule: the paid
options cost $22–$240/yr, replace only the first layer, and **cannot
demonstrate they cover the platform's primary market** before purchase.

## Caveats

- Google News gives **headlines and links, not full text** — no article body,
  no sentiment score, no symbol tagging. Relevance depends on query
  construction, so a bad query is a silent quality failure, not an error.
- It is a search feed, so a symbol whose name is an ordinary word ("ITC",
  "Titan") pulls unrelated stories. Queries need the disambiguating suffix that
  the scale test used.
- None of these sources is licensed for redistribution. Private single-operator
  use is not redistribution; publishing would be. Same standing note as 022.
