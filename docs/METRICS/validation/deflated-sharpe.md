# Deflated Sharpe ratio (DSR)

*Family: Validation and the gate. Id: `deflated-sharpe`.*

**In one line:** Probability that the true Sharpe is above zero, after counting how many things were tried.

**Where you see it:** Gate; validation report; `deflated_sharpe_probability`.

**How we compute it:** Φ[(SR − SR₀)√(n−1) / √(1 − skew·SR + (kurt/4)·SR²)], per-period units (`validation/statistics.deflated_sharpe`; `docs/ARCHITECTURE.md` §5.3).

**Data and freshness:** Daily returns, trial count.

**What is normal (our data, as of 2026-10-30):** The gate needs at least 0.95 (`mandate.yaml` (operator-owned)).

**How to read it:**

- A probability, not a ratio: 0.95 means a 95% chance it is not noise given the search.
- Negative skew and fat tails lower it.

**What it does not tell you:** Expected return.

**Traps:**

- Depends on the assumed σ_SR (A-021).
- Uses our zero-cash-rate Sharpe (A-083).

**Related:**

- [noise-bar](../validation/noise-bar.md)
- [skew-and-kurtosis](../performance/skew-and-kurtosis.md)
- [pbo](../validation/pbo.md)

**Sources:**

- Bailey & López de Prado (research 015).

## Example answers

**Q:** DSR 0.62?

**A:** A 62% chance the edge is real after the search, well short of the 95% the gate requires. Treat it as unproven.
