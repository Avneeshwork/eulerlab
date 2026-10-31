# At-the-money implied volatility (ATM IV)

*Family: Options. Id: `atm-implied-volatility`.*

**In one line:** The volatility the market prices into Nifty's nearest at-the-money options.

**Where you see it:** Options tab; brief scorecard row Options; `options.atm_iv`.

**How we compute it:** Black-76 implied volatility of the ATM strike nearest the forward, inverted from settlement prices (`options/iv.implied_vol`).

**Data and freshness:** F&O bhavcopy settlement prices.

**What is normal (our data, as of 2026-10-30):** Nifty nearest expiry, 34 sessions held (2026-09-10 to 2026-10-30), so these ranges are thin: median 12.6%, 5th-95th 9.1% to 17.2%.

**How to read it:**

- Close to India VIX but for one expiry, not a constant 30 days.
- Rising IV with a falling market is normal; rising IV with a rising market is unusual and worth noting.

**What it does not tell you:** Direction.

**Traps:**

- Near expiry, ATM IV is jumpy because little time value is left.
- Settlement prices can be stale for thin strikes.

**Related:**

- [india-vix](../market/india-vix.md)
- [implied-volatility](../options/implied-volatility.md)
- [volatility-smile](../options/volatility-smile.md)

**Sources:**

- Black (1976), Journal of Financial Economics 3: 167-179 (via Wikipedia's Black model page, 2026-10-31).

## Example answers

**Q:** ATM IV rose from 14.2% to 15.4%?

**A:** Option sellers are asking for more. That is near the top quarter of the last six weeks held, and fits the rise in VIX.
