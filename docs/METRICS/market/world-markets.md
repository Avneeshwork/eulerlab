# World markets: crude, gold, dollar, yields, rupee

*Family: Market context. Id: `world-markets`.*

**In one line:** Overnight moves in the global prices that feed Indian markets.

**Where you see it:** Brief detail World; Macro band.

**How we compute it:** Last price and change from TradingView's scanner (`macro.fetch`).

**Data and freshness:** Fetched at brief time; not stored as a history.

**What is normal (our data, as of 2026-10-30):** Not computed.

**How to read it:**

- Crude up hurts India's import bill and the rupee; a stronger dollar and higher US yields usually pull foreign money out of emerging markets.

**What it does not tell you:** Indian market direction on its own.

**Traps:**

- Snapshot time matters; say when it was taken.
- For yields, check whether a change is a percent of the yield or in basis points before quoting it; the feed does not say.

**Related:**

- [fii-dii-cash-flows](../market/fii-dii-cash-flows.md)

**Sources:**

- Research 004 (India macro data sources).

## Example answers

**Q:** Brent is up 2.4%. Does it matter for Nifty?

**A:** It is a cost for India, which imports most of its oil, and tends to weigh on the rupee and oil-consuming sectors. On its own it does not set the day's direction.
