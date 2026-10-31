# Sharpe ratio

*Family: Strategy performance. Id: `sharpe-ratio`.*

**In one line:** Average daily return divided by its standard deviation, scaled to a year.

**Where you see it:** Strategies table, every backtest report, the gate, paper cards; `sharpe`.

**How we compute it:** mean(r) / std(r) × √252 on daily returns, sample standard deviation (`validation/statistics.sharpe_stats`; `docs/ARCHITECTURE.md` §5.2). **No risk-free rate is subtracted.**

**Data and freshness:** The strategy's daily equity curve.

**What is normal (our data, as of 2026-10-30):** For context, `docs/ARCHITECTURE.md` §5.3 records a noise bar of 1.88 for the trials logged and a best-ever result of 1.27 at the time it was written. Check the live noise bar on the Strategies page.

**How to read it:**

- Return per unit of total volatility. Higher is better, but only against the noise bar for the number of things tried (see deflated Sharpe).
- Rule of thumb, not from a source: above 2 on daily data, look for an error or overfitting before believing it.

**What it does not tell you:** Drawdown size, tail risk, or whether it was luck.

**Traps:**

- **Zero risk-free rate.** Sharpe (1994) defines it on returns in excess of a riskless asset. Ours uses raw returns, which flatters any strategy that is mostly invested: at 15% volatility, a 6% cash rate is worth 0.4 of Sharpe. Recorded as A-083; whether to change it is the operator's decision (T-4249).
- √252 scaling assumes no serial correlation; Sharpe warns that a given sample may have it anyway.
- Sample vs population standard deviation: the skeptic agent uses `pstdev`, so its Sharpe can differ slightly from the report's.
- A strategy that holds cash most days has a lower Sharpe for the same edge; see invested fraction.

**Related:**

- [deflated-sharpe](../validation/deflated-sharpe.md)
- [sortino-ratio](../performance/sortino-ratio.md)
- [max-drawdown](../performance/max-drawdown.md)
- [noise-bar](../validation/noise-bar.md)

**Sources:**

- Sharpe (1994), The Sharpe Ratio, Journal of Portfolio Management 21(1): https://web.stanford.edu/~wfsharpe/art/sr/sr.htm (fetched 2026-10-31).

## Example answers

**Q:** Sharpe 1.27. Good?

**A:** On its face, yes, but not after counting how many configurations were tried: the noise bar for the trials logged is 1.88, so pure noise would be expected to do better than this by luck. Also, our Sharpe does not subtract a cash rate, which flatters it further.

**Q:** Why does the skeptic show a different Sharpe from the report?

**A:** Two reasons that are both legitimate: it uses the population standard deviation, and it may run over a different set of days. The gap should be small; a big one is worth checking.
