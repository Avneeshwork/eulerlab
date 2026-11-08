# ADR-154 — Angel One as a second order path and a quote fallback

**Context.** Operator, 2026-11-08: "check also to place order on angel one". Kite's token dies at 06:00 and needs a person at Zerodha's login page each morning, so a missed login is a missed live-price session (T-4526). `broker/smartapi.py` already implemented `BrokerAdapter` for Angel One but had never been run, and the Angel login (PIN plus TOTP seed in `.env`) needs no person.

**Options.** Kite only; replace Kite with Angel; or keep both, with Angel as the quote fallback and an equal way to prove the order path.

**Choice.** `broker/angel_check.py`: `make angel-readonly` logs in, reads profile, funds, order book, positions, one full quote and Angel's intraday (MIS) list, sends nothing, and writes `data/oms/angel_readonly.json` with no secrets. `make angel-proof SYMBOL=SBIN CONFIRM=SEND` is the operator's one-share MIS round trip through `SmartAPIBroker`, refused without `CONFIRM=SEND`, with the kill switch tripped, on a weekend, or outside 09:20–15:00 IST; it writes `data/oms/angel_proof.json` only when both legs complete. `deploy/live_shadow.py` uses Angel quotes when Kite has no fresh token, and records `quote_source`. `deploy/readiness.py` accepts either broker's proof ("broker order path proved").

**Why.** Two brokers remove the morning login as a single point of failure, and the proof stays a supervised, explicit act.

**Cost if wrong.** The `getMarketData` FULL reply shape and 50-token limit are unverified (A-127); the parser refuses an unknown shape, so a wrong guess shows as a "no quotes" morning, not a wrong number. Angel and Kite quotes can differ by a tick; a session whose open and close came from different brokers mixes sources. A buy that fills and a sell that does not leaves one share held MIS; the tool says so and Angel squares it off at its cut-off.
