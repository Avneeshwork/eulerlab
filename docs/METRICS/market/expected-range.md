# One-day range from VIX

*Family: Market context. Id: `expected-range`.*

**In one line:** The band Nifty would stay inside on about two days in three if VIX were right.

**Where you see it:** Brief → Today's map.

**How we compute it:** close × VIX / 100 / √252 either side of the last close (`agents/trader_read._map`).

**Data and freshness:** Last Nifty 50 close and India VIX close.

**What is normal (our data, as of 2026-10-30):** With the past year's median VIX (13.2), about ±0.83% of the index.

**How to read it:**

- Inside the band is an ordinary day. A close outside it is a one-in-three day; twice the band is about one in twenty.
- Compare with the straddle range, which covers to expiry, not one day.

**What it does not tell you:** A target. It assumes normal returns, and real ones have fatter tails.

**Traps:**

- It is a one-standard-deviation band, not a limit.
- Using it on an expiry day mixes it with pinning effects.

**Related:**

- [india-vix](../market/india-vix.md)
- [straddle-expected-move](../options/straddle-expected-move.md)

**Sources:**

- Standard conversion of annualised volatility to one day by √252 (Sharpe 1994 discusses the same time-scaling assumption: https://web.stanford.edu/~wfsharpe/art/sr/sr.htm, fetched 2026-10-31).

## Example answers

**Q:** What's today's likely range?

**A:** If VIX is right, Nifty stays between 22,831 and 23,275 on about two days in three (±222 around 23,053). A close outside that would be unusual but not rare.
