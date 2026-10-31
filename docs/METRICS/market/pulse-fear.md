# Fear card

*Family: Market context. Id: `pulse-fear`.*

**In one line:** Elevated, Normal or Calm from India VIX's one-year percentile.

**Where you see it:** Dashboard pulse.

**How we compute it:** Above the 70th percentile Elevated; under the 30th Calm; else Normal (our thresholds) (`market_pulse.fear_card`).

**Data and freshness:** India VIX.

**What is normal (our data, as of 2026-10-30):** By construction, Elevated about 30% of days.

**How to read it:**

- Elevated means option protection is dearer than usual.

**What it does not tell you:** Direction.

**Traps:**

- The thresholds are ours, not from a source.

**Related:**

- [india-vix](../market/india-vix.md)

**Sources:**

- ADR-081.

## Example answers

**Q:** Fear: Elevated. Should I worry?

**A:** It means VIX is in the top 30% of the past year, so swings are expected to be larger than usual. It is not a forecast of a fall.
