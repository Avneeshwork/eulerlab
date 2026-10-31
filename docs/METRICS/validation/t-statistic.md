# t-statistic of the strategy's mean return

*Family: Validation and the gate. Id: `t-statistic`.*

**In one line:** How many standard errors the average return is from zero.

**Where you see it:** Skeptic agent (`t_stat`); trial ledger rows. **Not checked by the gate today** (see traps).

**How we compute it:** mean / (std / √n) of daily returns with the population standard deviation (`agents/workers/skeptic.attacks`); about Sharpe × √years.

**Data and freshness:** Daily returns.

**What is normal (our data, as of 2026-10-30):** `mandate.yaml` (operator-owned) sets `min_t_statistic: 3.0`, following Harvey, Liu & Zhu's argument for a higher bar when many factors have been tried.

**How to read it:**

- Under 2: indistinguishable from luck even before counting trials.

**What it does not tell you:** Size of the edge.

**Traps:**

- **`gates.py` never reads `min_t_statistic`.** The mandate lists it but no code checks it, so a strategy is not killed for a t below 3 (found 2026-10-31; HISTORY #42, T-4250). Both files are operator-owned.
- Grows with the length of history; a long test of a tiny edge can pass.

**Related:**

- [deflated-sharpe](../validation/deflated-sharpe.md)
- [beta-and-alpha](../performance/beta-and-alpha.md)

**Sources:**

- Harvey, Liu & Zhu, …and the Cross-Section of Expected Returns: NBER w20592, https://www.nber.org/papers/w20592 (research 015).

## Example answers

**Q:** t = 2.4, isn't that significant?

**A:** At the usual 5% level for one test, yes. With many strategies tried, Harvey, Liu and Zhu argue the bar should be about 3. Our mandate writes 3.0, but the gate does not check it yet (T-4250).
