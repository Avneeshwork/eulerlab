# 024 — Alpaca: what these keys actually reach

**Question.** What can this platform fetch, store and stream from Alpaca, and
what does it cost?

**Probed 2026-08-24** with the `Alpaca_Key` / `Alpaca_Secret` already in `.env`.
Every line below is a measured response, not a documentation claim.

## What the keys are

**Paper trading keys.** `paper-api.alpaca.markets/v2/account` returns an
account; `api.alpaca.markets/v2/account` returns **401**. So orders can be
placed against the paper venue and not the live one — which is the right way
round for a platform whose deploy path is still `paper` by default.

Market data is unaffected by that: the data API answered every endpoint tried.

## Reachable, measured

| Endpoint | Result |
|---|---|
| `/v2/stocks/{sym}/bars` | ✅ daily bars back to **2016-01-04** at least |
| `/v2/stocks/bars?symbols=` | ✅ **multi-symbol**, 4 symbols in one call |
| 1Min bars | ✅ |
| `feed=iex` and `feed=sip` | ✅ **both** answered |
| `/v2/stocks/{sym}/snapshot` | ✅ latest trade, quote, minute bar, daily bar, prev daily |
| `/v2/stocks/{sym}/quotes/latest` | ✅ |
| `/v1beta1/news` | ✅ headline, summary, **content**, symbols, source, author |
| `/v1beta3/crypto/us/bars` | ✅ |
| `/v1beta1/options/snapshots/{sym}` | ✅ |
| `/v1/corporate-actions` | ✅ |
| `/v2/assets` | ✅ 6.4 MB of active US equities |

## What this changes

### The US price panel stops being a project

T-3733 and the "US panel not started" item have been open on the grounds that
FMP's free EOD is one call per symbol against a 250-a-day budget. Alpaca is
**multi-symbol and unmetered by comparison**: a 500-name US universe over ten
years is a few hundred paginated calls, not a multi-day rationing exercise.

That makes a real US panel — breadth, a constituent map, a session line — a
day of ingest work rather than an open question.

### News, free, with the article body

FMP answers **402** on every news endpoint. Alpaca returns headline, summary
**and content**, tagged with symbols. The Google News layer this platform built
gives headlines and links only, and its relevance has to be inferred from the
title because there is nothing else. Alpaca's rows carry the tickers the
publisher assigned.

That does not replace Google News — Alpaca covers US listings, and this
platform's first market is NSE — but for anything US-listed it is strictly
better data.

### Options and corporate actions are new categories

Neither has ever been reachable here. Options snapshots would give the chain
this platform has recorded as absent since ADR-035. Corporate actions are the
thing the equity panel's adjustment depends on, and it currently infers them.

## What could be live

Alpaca publishes WebSocket streams for trades, quotes, bars and news. **Not
tested** — the probe was REST only, and a streaming client is a different piece
of work with its own supervision problem. Recorded as reachable in principle,
unverified in fact.

The honest near-term live path is the same one the rest of this platform uses:
poll the snapshot endpoint on demand, cache briefly, and say when it was taken.

## What was not established

- **Rate limits.** Alpaca documents 200 requests/minute on the free plan; this
  probe made twenty and hit nothing, so the ceiling is untested.
- **Whether `sip` is genuinely entitled.** Both feeds answered, which is
  surprising — SIP is the paid consolidated tape. A single 200 does not prove
  entitlement across a real backfill, and building on it before confirming
  would be building on an accident.
- **Streaming.** Not attempted.
- **Options depth.** One snapshot call succeeded; chain coverage and history
  are unmeasured.

## Recommendation, in order

1. **US daily panel** from multi-symbol bars — closes the oldest open item and
   makes the US tab a real market rather than a quote ribbon.
2. **US news** into the existing news store, which already has the schema.
3. **Corporate actions**, which improve an adjustment the panel currently
   infers.
4. **Options and streaming** last: both are new subsystems, and neither is
   needed for anything the platform does today.
