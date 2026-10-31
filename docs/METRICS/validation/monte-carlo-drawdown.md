# Monte Carlo: shuffled drawdowns and bootstrapped Sharpe

*Family: Validation and the gate. Id: `monte-carlo-drawdown`.*

**In one line:** How bad the drawdown could have been with the same returns in another order, and how uncertain the Sharpe is.

**Where you see it:** Validation report; `make montecarlo`.

**How we compute it:** Shuffle: reorder returns, read the drawdown distribution. Bootstrap: resample with replacement for a Sharpe interval (`validation/montecarlo.py`; `docs/ARCHITECTURE.md` §5.6a).

**Data and freshness:** Daily returns.

**What is normal (our data, as of 2026-10-30):** Example recorded: `momentum_12_1` Sharpe 0.11, bootstrap 5th percentile −0.96.

**How to read it:**

- If the realised drawdown is shallower than the median shuffled path, the bad ordering has not happened yet.

**What it does not tell you:** Clustering of losses: shuffling breaks it, so this is a lower bound on risk.

**Traps:**

- Does not spend a trial; it evaluates nothing new.

**Related:**

- [max-drawdown](../performance/max-drawdown.md)

**Sources:**

- ADR-034; `docs/ARCHITECTURE.md` §5.6a.

## Example answers

**Q:** Monte Carlo median drawdown 25%, backtest showed 15%?

**A:** The backtest was lucky in the order its losses came. Plan for about 25%, and remember shuffling understates clustered crashes.
