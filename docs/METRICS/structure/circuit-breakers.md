# Circuit breakers and price bands

*Family: Market structure and trading rules. Id: `circuit-breakers`.*

**In one line:** Market-wide halts at 10%, 15% and 20% index moves, and per-stock daily price limits.

**Where you see it:** Data quality checks (circuit-hit days); research 100.

**How we compute it:** Market-wide: Nifty or Sensex moves of 10%, 15% or 20% from the previous close halt all equity and equity derivative trading for set times depending on the time of day; a 20% move stops trading for the day (SEBI 2001, NSE table). Stocks have their own price bands.

**Data and freshness:** NSE.

**Do we hold it:** Price data shows circuit days; bands are not stored separately.

**What is normal (our data, as of 2026-10-30):** Market-wide halts are rare.

**How to read it:**

- A stock at its upper or lower circuit cannot be traded through; a backtest that fills at that price is unrealistic.

**What it does not tell you:** Direction after the halt.

**Traps:**

- Rules change; check NSE or SEBI before quoting (A-085).
- Third-party guides give different halt durations; use NSE's table.

**Related:**

- [trading-sessions](../structure/trading-sessions.md)

**Sources:**

- NSE equity market circuit breakers page; SEBI circular SMDRPD/Policy/Cir-37/2001 (search summary, 2026-10-31); research 100.

## Example answers

**Q:** Can I sell a stock stuck at lower circuit?

**A:** Only if a buyer appears at that price; usually sellers queue with no buyers, so the backtest's fill is not achievable.
