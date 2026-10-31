# Option greeks: delta, gamma, theta, vega

*Family: Options. Id: `greeks`.*

**In one line:** How an option's price changes with the index, with time, and with volatility.

**Where you see it:** Options chain and payoff builder.

**How we compute it:** Black-76 greeks per strike (`options/iv.greeks`).

**Data and freshness:** Bhavcopy or live quotes.

**What is normal (our data, as of 2026-10-30):** Per strike; no market-wide normal.

**How to read it:**

- Delta: option change per 1-point index move (also a rough chance of finishing in the money).
- Gamma: how fast delta changes; largest at the money near expiry.
- Theta: daily time decay. Vega: change per 1 point of volatility.

**What it does not tell you:** Profit or loss on its own.

**Traps:**

- Model numbers; they assume the IV used is right.

**Related:**

- [implied-volatility](../options/implied-volatility.md)
- [gamma-exposure](../options/gamma-exposure.md)

**Sources:**

- Black (1976).

## Example answers

**Q:** What does delta 0.5 mean?

**A:** The option moves about half a point for each point Nifty moves, and the model gives it roughly even odds of ending in the money.
