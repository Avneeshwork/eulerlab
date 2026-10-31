# Maximum drawdown, and time to trough and recovery

*Family: Strategy performance. Id: `max-drawdown`.*

**In one line:** The largest fall from a previous high, and how long it took to fall and to recover.

**Where you see it:** Every report, paper cards, risk; `max_drawdown`, `drawdown`, `days_to_trough`.

**How we compute it:** min over t of equity(t) / max(equity up to t) − 1 (`validation/montecarlo.max_drawdown`; `docs/ARCHITECTURE.md` §5.6a). Live books use the time-weighted index.

**Data and freshness:** Equity curve or the time-weighted index.

**What is normal (our data, as of 2026-10-30):** The loss limits act at 10% (reduce-only) and 20% (halt) by default (A-071).

**How to read it:**

- The pain you would have sat through. Ask whether you would have kept running it at that point.
- Monte Carlo shows how much worse it could have been with the same returns in a different order.

**What it does not tell you:** Probability of a repeat.

**Traps:**

- One history gives one drawdown; the next can be larger.
- Raw equity with flows overstates it.

**Related:**

- [monte-carlo-drawdown](../validation/monte-carlo-drawdown.md)
- [loss-limits](../risk/loss-limits.md)
- [time-weighted-return](../performance/time-weighted-return.md)

**Sources:**

- `docs/ARCHITECTURE.md` §5.6a.

## Example answers

**Q:** Max drawdown 22%. Acceptable?

**A:** It would have tripped the default 20% halt. Over one history; Monte Carlo reshuffles suggest how much deeper the same returns could go.
