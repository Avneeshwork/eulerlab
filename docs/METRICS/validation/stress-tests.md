# Stress tests: 2× costs, drop best names, worst regime, delay

*Family: Validation and the gate. Id: `stress-tests`.*

**In one line:** Share of Sharpe that survives when conditions get worse.

**Where you see it:** Gate; validation report.

**How we compute it:** `validation/stress.py`: cost multiple on every charge, drop the best contributors, by-regime split, execution delay (`docs/ARCHITECTURE.md` §5.6).

**Data and freshness:** Re-runs of the backtest.

**What is normal (our data, as of 2026-10-30):** Gate: ≥ 60% of Sharpe at 2× costs, ≥ 60% without the best names, ≥ 50% in the worst regime, no negative stress (`mandate.yaml` (operator-owned)).

**How to read it:**

- A strategy that only works in one regime or on five names is fragile.

**What it does not tell you:** Probability of those conditions.

**Traps:**

- The cost stress once scaled only brokerage (zero on delivery); fixed (`docs/ARCHITECTURE.md` §5.6).

**Related:**

- [sharpe-without-best-year](../performance/sharpe-without-best-year.md)
- [turnover-and-costs](../performance/turnover-and-costs.md)

**Sources:**

- `docs/ARCHITECTURE.md` §5.6.

## Example answers

**Q:** Keeps 40% of Sharpe at 2× costs?

**A:** It fails the 60% bar: the edge is mostly eaten by trading costs.
