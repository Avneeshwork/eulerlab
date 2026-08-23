# 022 — Financial Modeling Prep: what the free plan actually gives

**Question.** The operator asked to fetch FMP's news API and work out what is
worth taking on the free tier. Can this platform get stock-specific news —
the gap the trader snapshot still has — without paying?

**Fetched 2026-08-23.**

## Sources

| What | URL | Read |
|---|---|---|
| Endpoint reference | https://site.financialmodelingprep.com/developer/docs/stable | 2026-08-23 |
| Pricing and plan matrix | https://site.financialmodelingprep.com/developer/docs/pricing | 2026-08-23 |

Both return **403 to a plain fetch** and render only in a real browser, so they
were read through one. Worth noting for anyone re-checking: a scripted
verification of these pages will look like the site is down.

## Findings

### The free plan, as published

| | Basic (free) | Starter ($22/mo) |
|---|---|---|
| Calls | **250 / day** | 300 / minute |
| Bandwidth | **500 MB / 30 days** | 20 GB |
| Timeframe | **End of day** | Real-time |
| History | 5 years | 5 years |
| Coverage | — | US |

### News is not in the free tier

The plan card lists **"Financial Market News"** and **"Crypto and Forex"** as
Starter features. On the published matrix, the news endpoints are precisely the
thing the free plan excludes. This is the direct answer to the question asked,
and it is not the convenient one.

### The `demo` key is retired

FMP's docs historically used `apikey=demo` for AAPL examples. All twenty
endpoints probed on 2026-08-23 returned **401 Invalid API KEY**, including the
plain `v3/profile/AAPL` that the demo key used to serve. There is no
key-less way to verify the tier boundary.

### What exists, if a key is obtained

258 documented `stable/` endpoints. The news family:

```
news/general-latest      news/stock-latest      news/press-releases-latest
news/crypto-latest       news/forex-latest      fmp-articles
news/stock?symbols=      news/crypto?symbols=   news/forex?symbols=
```

`news/stock?symbols=` is the one that would close the snapshot's real gap — a
mover with no reason next to it. The rest are context.

Beyond news, the endpoints that would fill known holes: `quote?symbol=^GSPC`
(index levels, which the snapshot has never had), `biggest-gainers` /
`biggest-losers` / `most-actives`, `sector-performance-snapshot`, and
`economic-calendar` — which unlike the ForexFactory feed **has a date range**,
so it could backfill the history that feed cannot.

### What could not be determined

**Whether a free key returns news at all.** Creating the account is the
operator's action, not mine. The plan matrix says no; vendors move endpoints
between tiers and pricing pages go stale, so the matrix is evidence, not proof.

`make fmp-probe` resolves it in one command: it asks twenty-five endpoints what
they answer and prints reachable / empty / refused, spending ten calls' worth
of a 250-call day. The code trusts that measurement, not this document.

## Decision

Wrote `src/eulerlab/ingest/fmp.py` against the documented schema, with the
budget as a first-class argument rather than a comment — on 250 calls a day a
fifteen-minute poll of one endpoint is 96 calls, and two are the whole day.
Nothing is scheduled and `make daily` is untouched until a probe says there is
something to fetch.

**Confidence: high** on the plan limits and the endpoint list, both read from
the vendor's own pages. **Low** on whether a free key serves news, which is
unresolved by design rather than by omission.

## Open questions

1. Does a free key return `news/general-latest`? One `make fmp-probe` away.
2. Is `economic-calendar` free? If so it beats the ForexFactory feed outright,
   which has no history endpoint and no `actual` value — see
   `docs/RESEARCH/021` and T-3725.
3. FMP's terms require a separate licensing agreement to **display or
   redistribute** their data. A single-operator private terminal is not
   redistribution; anything shared later would be. Recorded, not resolved.
4. India coverage is untested. US coverage starts at Starter, and the platform's
   first market is NSE — so even a paid tier may not cover the instruments that
   matter most here.
