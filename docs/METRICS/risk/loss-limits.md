# Loss limits: reduce-only and halt

*Family: Risk on the live book. Id: `loss-limits`.*

**In one line:** A deployment's drawdown from its own high against the levels that change what it may do.

**Where you see it:** Live & Risk cards; the brief's books ('reduce-only at 10%').

**How we compute it:** Drawdown from the time-weighted curve; at `reduce_at` (10%) buys are refused from the next session; at `halt_at` (20%) the kill switch trips (`deploy/loss_limits.apply`; ADR-092).

**Data and freshness:** Deployment state, after every run.

**What is normal (our data, as of 2026-10-30):** Defaults 10% and 20% (`config/loss_limits.yaml`, A-071).

**How to read it:**

- A book at 9.4% is one bad day from reduce-only.

**What it does not tell you:** Whether the strategy is broken.

**Traps:**

- Raw equity counts withdrawals as losses; always the time-weighted figure (HISTORY #40).
- Only the daily rebalancing book enforces reduce-only (S-050).

**Related:**

- [max-drawdown](../performance/max-drawdown.md)
- [time-weighted-return](../performance/time-weighted-return.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Loss limits that act (ADR-092).

## Example answers

**Q:** Which book is closest to its limit?

**A:** The ₹10,000 india_sharpe_momentum_opt book: 9.4% below its peak, against reduce-only at 10%.
