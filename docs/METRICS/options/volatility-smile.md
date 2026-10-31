# Volatility smile and skew

*Family: Options. Id: `volatility-smile`.*

**In one line:** Implied volatility across strikes for one expiry.

**Where you see it:** Options charts; `options/analytics.smile`.

**How we compute it:** IV per strike against moneyness from the forward.

**Data and freshness:** Bhavcopy.

**What is normal (our data, as of 2026-10-30):** On Nifty, put IVs below spot are usually higher than call IVs above it.

**How to read it:**

- A steeper put side means more demand for crash protection.

**What it does not tell you:** Direction.

**Traps:**

- Thin far strikes give unreliable IVs.

**Related:**

- [implied-volatility](../options/implied-volatility.md)

**Sources:**

- Black (1976).

## Example answers

**Q:** The skew steepened. Meaning?

**A:** Out-of-the-money puts got dearer relative to at-the-money options: more demand for downside protection.
