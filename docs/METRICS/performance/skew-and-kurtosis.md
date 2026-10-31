# Skew and excess kurtosis

*Family: Strategy performance. Id: `skew-and-kurtosis`.*

**In one line:** Whether returns lean to big losses or big gains, and how fat the tails are.

**Where you see it:** Reports; validation; `skew`, `kurtosis`, `excess_kurtosis`.

**How we compute it:** Third and fourth standardised moments of daily returns; kurtosis minus 3 (`validation/statistics.sharpe_stats`; `docs/ARCHITECTURE.md` §5.2).

**Data and freshness:** Daily returns.

**What is normal (our data, as of 2026-10-30):** Normal returns: both 0. Most strategies: negative skew, positive kurtosis.

**How to read it:**

- Negative skew and high kurtosis shrink the deflated Sharpe, correctly.

**What it does not tell you:** Sign of future tail events.

**Traps:**

- A single extreme day can dominate both; check the worst day.

**Related:**

- [deflated-sharpe](../validation/deflated-sharpe.md)

**Sources:**

- `docs/ARCHITECTURE.md` §5.2.

## Example answers

**Q:** Kurtosis 155?

**A:** Extremely fat tails, usually one or two enormous days or a data error. ARCHITECTURE notes one such configuration not fully explained (T-1310).
