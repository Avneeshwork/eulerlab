# 074 — How many instruments, how often, can Kite be asked for quotes?

**Question.** The dashboard's live map asked Kite for 2,900 symbols in 16
calls of 200 and took 3 to 5 seconds (T-4064). Can it ask for more at once?

## Sources, fetched 2026-10-12

| Source | URL | What it says |
|---|---|---|
| Kite Connect, Market quotes | https://kite.trade/docs/connect/v3/market-quotes/ | `/quote`: "the complete market data snapshot of up to 500 instruments in one go". `/quote/ohlc`: "the OHLC + LTP snapshots of up to 1000 instruments in one go". `/quote/ltp`: "the LTPs of up to 1000 instruments in one go" |
| Kite Connect, Exceptions and errors | https://kite.trade/docs/connect/v3/exceptions/ | Rate limits: Quote 1 request a second; historical candle 3; order placement 10; all other endpoints 10 |

## Measured, 2026-10-12, 2,352 NSE symbols

| Call | Batches | Time | Priced |
|---|---|---|---|
| `quote()`, 200 a call (as it was) | 12 | 3.84 s | 2,154 |
| `ohlc()`, 1,000 a call | 3 | HTTP 400 Bad Request | 0 |
| `ohlc()`, 500 a call | 5 | 0.83 s | 2,154 |

The 1,000 batch fails although documented: the instruments are sent in the
URL, and 1,000 NSE symbols make it too long. RELIANCE read the same from both
endpoints (last 1158.0, previous close 1170.3).

## Findings

- The live map needs the last price and the previous close. `/quote/ohlc`
  carries both; `/quote` also carries depth, which the map does not use.
- The old code sent 12 to 16 quote requests back to back, against a
  documented limit of one a second. Kite tolerated it; it was not within the
  stated limit. Five requests is closer and is still above one a second.

## What could not be found

- Whether the one-a-second limit is enforced per endpoint or per endpoint
  family, and what Kite does on a breach (the page lists the limit only).
- The longest URL Kite accepts.

## Decision

`quotes.nse_universe` uses `ohlc()` with `UNIVERSE_BATCH = 500`. The calls are
not sent side by side: that would only press harder on a limit already
exceeded. A-055 records the rate-limit exposure.

## Confidence

High on the documented limits and the measurements. Low on enforcement.
