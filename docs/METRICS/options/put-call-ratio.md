# Put-call ratio (PCR) by open interest

*Family: Options. Id: `put-call-ratio`.*

**In one line:** Open put contracts divided by open call contracts on Nifty's nearest expiry.

**Where you see it:** Options tab; brief scorecard row Options; `options.pcr_oi`, `pcr_oi_before`.

**How we compute it:** Sum of put OI / sum of call OI across strikes (`options/analytics.put_call_ratio`). By volume is computed separately and never averaged with it.

**Data and freshness:** F&O bhavcopy, end of day; nearest expiry after the trade date.

**What is normal (our data, as of 2026-10-30):** Nifty nearest expiry, 34 sessions held (2026-09-10 to 2026-10-30), so these ranges are thin: median 0.93, 25th-75th 0.72 to 1.13, 5th-95th 0.60 to 1.62.

**How to read it:**

- Above 1: more puts open than calls. Much of Nifty put OI is written (sold) puts, which many read as support; others read it as hedging demand. Both readings are in use.
- A fast move matters more than the level: 0.70 to 1.04 in a week means a lot of put open interest was added.

**What it does not tell you:** Direction with any proven reliability for index options.

**Traps:**

- Pan & Poteshman's evidence that put-call ratios predict returns is for buyer-opened single-stock volume, and a secondary summary of the paper reports no such effect for index options. Do not cite it for Nifty PCR.
- Sensibull itself says PCR and max pain do not have high predictive power (research 120).
- Expiry week distorts it: OI shrinks and shifts to the next expiry.

**Related:**

- [max-pain](../options/max-pain.md)
- [atm-implied-volatility](../options/atm-implied-volatility.md)

**Sources:**

- Pan & Poteshman (2006), Review of Financial Studies 19(3): NBER w10925 abstract, https://www.nber.org/papers/w10925 (fetched 2026-10-31).
- Research 120 (Sensibull).

## Example answers

**Q:** PCR went from 0.70 to 1.04. Bullish?

**A:** It means far more puts are open than a week ago. Traders read that both ways (put writers defending a level, or buyers hedging). On index options there is no solid evidence it predicts direction, so treat it as positioning, not a signal.
