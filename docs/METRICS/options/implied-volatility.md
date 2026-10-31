# Implied volatility (any strike)

*Family: Options. Id: `implied-volatility`.*

**In one line:** The volatility that makes the Black-76 price equal the option's market price.

**Where you see it:** Options chain, smile chart, payoff builder.

**How we compute it:** Bisection on Black-76 with the futures forward and a discount factor (`options/iv.py`).

**Data and freshness:** Bhavcopy or live quotes.

**What is normal (our data, as of 2026-10-30):** See ATM IV; away from the money it is usually higher on puts (skew).

**How to read it:**

- Higher IV means a dearer option for the same strike and time.

**What it does not tell you:** Realised volatility to come.

**Traps:**

- On single-stock options, expected dividends before expiry change the forward; using the index method unchanged misprices them.

**Related:**

- [atm-implied-volatility](../options/atm-implied-volatility.md)
- [volatility-smile](../options/volatility-smile.md)
- [greeks](../options/greeks.md)

**Sources:**

- Black (1976).

## Example answers

**Q:** Why is the 22,000 put IV higher than ATM?

**A:** Downside protection is in steady demand, so out-of-the-money puts trade at a higher implied volatility than at-the-money options. That is the usual skew, not a sign of anything new on its own.
