# 069 — How other platforms run a paper or sandbox account, and what they do when it breaks

**Question.** Operator, 2026-10-07: "build full paper trading infra mimicking
live trading and deploy first, research other platform sandbox / paper trading
and fallback system". What does a paper account simulate elsewhere, what does
it leave out, and what happens on failure?

## Sources, fetched 2026-10-07

| Source | URL | What it says |
|---|---|---|
| Alpaca, Paper Trading docs | https://docs.alpaca.markets/docs/paper-trading | Same API end to end; fills against the live NBBO; random partial fills 10% of the time; default $100k, resettable. Does **not** simulate dividends, market impact, regulatory fees, latency slippage or queue position |
| OpenAlgo, API Analyzer | https://docs.openalgo.in/new-features/api-analyzer | One API for both modes, switched by an analyzer flag. Sandbox state (orders, trades, positions, funds) in a separate store; virtual capital (default ₹1 crore); MARKET fills at current price, LIMIT/stop rest until crossed; margins and auto square-off simulated. Prices from the live broker feed; cannot replicate broker delays, partial fills or microstructure |
| QuantConnect, Live Trading — getting started | https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/getting-started | Paper brokerage fills like a backtest, immediately and completely. A restart re-runs `Initialize` and recovers only cash, holdings and some open orders; automatic restart on runtime errors or broker disconnects, up to five attempts; a Liquidate button as the kill switch |
| Upstox community, sandbox vs prod | https://community.upstox.com/t/sandbox-vs-prod-data-credentials-and-migration/10369 | Upstox's sandbox only checks request format: a mock success, no positions, no fills, no order book |
| Kite Connect forum, sandbox tag | https://kite.trade/forum/discussions/tagged/sandbox | Zerodha has no sandbox ("on our roadmap", depends on their OMS vendor). Developers test after hours, with an unfunded account, or with their own simulator |

Search snippets were used to find these pages; each claim above is from the
page itself, except the Kite forum, which was read through search results only.

## Findings

1. **The good sandboxes run the live code path with a simulated broker
   underneath** (Alpaca, OpenAlgo). Ours already has that shape: the same
   OMS, journal, kill switch and order ids, with `PaperBroker` in place of the
   Kite adapter.
2. **None simulates everything.** All three state what they leave out. Ours
   leaves out: partial fills (S-016), market impact (T-907), corporate actions
   on the paper book (S-038); it fills at the next close plus fixed adverse
   slippage (A-048).
3. **Indian brokers offer nothing usable.** Zerodha has no sandbox, and
   Upstox's checks only the request format. A paper account in India has to be
   built by the platform, which is what OpenAlgo did.
4. **Fallbacks elsewhere are restart-and-recover**: QuantConnect restarts and
   recovers cash and holdings from the broker; OpenAlgo keeps sandbox state in
   its own store. Neither describes what happens when history changes under a
   running strategy.

## Decision

ADR-060. A deployment replays from its start through the backtest engine with
the OMS in the middle, so restart, catch-up and recovery are the same act, and
the broker is checked against the book on every run. Any disagreement halts
that deployment; nothing restarts on its own.

**Confidence:** high on what each platform documents; their internals were not
inspected.
