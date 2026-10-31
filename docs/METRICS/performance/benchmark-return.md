# Benchmark comparison (Nifty return over the same window)

*Family: Strategy performance. Id: `benchmark-return`.*

**In one line:** What Nifty did over exactly the strategy's test window.

**Where you see it:** Strategies table; `nifty_return`.

**How we compute it:** Nifty total over the test's first to last day.

**Data and freshness:** Index history.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- A strategy that beats Nifty with more drawdown may not be better.

**What it does not tell you:** Risk-adjusted comparison.

**Traps:**

- Price index, not total return, so it understates Nifty by the dividend yield.

**Related:**

- [total-and-annual-return](../performance/total-and-annual-return.md)
- [beta-and-alpha](../performance/beta-and-alpha.md)

**Sources:**

- Index history.

## Example answers

**Q:** It made 60%; Nifty made 55%.

**A:** A small lead before counting Nifty's dividends (about 1.3% a year) and the extra drawdown. Compare Sharpe and drawdown too.
