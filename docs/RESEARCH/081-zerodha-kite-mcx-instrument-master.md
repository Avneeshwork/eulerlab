# 081 — Fetching the current MCX instrument master from Kite

**Question.** Which Kite endpoint returns the current MCX contracts and fields, and how should EulerLab retain the snapshot?

**Sources, fetched 2026-10-15.**

| Source | URL | Finding |
|---|---|---|
| Kite Connect, Market data and instruments | https://kite.trade/docs/connect/v3/market-data-and-instruments/ | `GET /instruments/:exchange` returns an exchange-filtered CSV; the listed columns include instrument token, tradingsymbol, expiry, strike, tick size, lot size, instrument type, segment and exchange. MCX is shown in the CSV example. The docs recommend storing a daily copy and warn that derivative tokens can be reused after expiry. |

**Finding.** `/instruments/MCX` is the documented exchange-specific endpoint. This is a current daily tradable instrument snapshot; the endpoint does not provide historical contract terms.

**Decision.** Fetch once per IST calendar date with the existing Kite API key and current access token, validate that the response has MCX rows and the required contract fields, preserve the response bytes in the immutable landing zone, and mirror the `mcx` tree under B2's `nse/mcx/` key prefix.

**Confidence.** High for the endpoint and response schema from Kite's documentation. The live response is validated at ingest time.

**Open question.** Kite's daily master is not a historical source. Historical MCX lot sizes, expiries and contract availability require an exchange archive or another point-in-time source before any backtest can rely on them.
