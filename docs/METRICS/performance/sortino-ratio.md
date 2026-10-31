# Sortino ratio

*Family: Strategy performance. Id: `sortino-ratio`.*

**In one line:** Like Sharpe, but only losing days count as risk.

**Where you see it:** Backtest reports; `sortino`.

**How we compute it:** mean(r) × 252 / √(mean of r² over losing days × 252) (`reports.py`). No minimum acceptable return is subtracted.

**Data and freshness:** Daily returns.

**What is normal (our data, as of 2026-10-30):** Higher than Sharpe when losses are smaller than gains.

**How to read it:**

- Use beside Sharpe: a big gap means the volatility is mostly upside.

**What it does not tell you:** Tail risk on its own.

**Traps:**

- **Our downside deviation averages over losing days only.** Sortino & Price's downside deviation averages over all periods (gains count as zero). Ours is therefore larger and our Sortino lower than the textbook value, by about √(share of losing days). Compare Sortino only within this platform.
- No minimum acceptable return, like the zero cash rate in Sharpe.

**Related:**

- [sharpe-ratio](../performance/sharpe-ratio.md)

**Sources:**

- Sortino & Price (1994), Journal of Investing 3(3); formula via PerformanceAnalytics documentation (search, 2026-10-31).

## Example answers

**Q:** Sortino 0.9 but Sharpe 1.1. How?

**A:** Our Sortino averages losses over losing days only, which makes it run lower than the textbook version. Within the platform, a Sortino below Sharpe means the losing days are relatively large.
