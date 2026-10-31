# Noise bar (expected maximum Sharpe of N worthless strategies)

*Family: Validation and the gate. Id: `noise-bar`.*

**In one line:** The Sharpe the best of N pure-noise strategies would show; the bar a real one must beat.

**Where you see it:** Strategies page; gate; `expected_max_sharpe`.

**How we compute it:** SR₀ = σ_SR × [(1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e))], γ ≈ 0.5772 (`validation/statistics.expected_max_sharpe`; `docs/ARCHITECTURE.md` §5.3).

**Data and freshness:** Trial count; σ_SR.

**What is normal (our data, as of 2026-10-30):** At the time `docs/ARCHITECTURE.md` was written: 1.88 for 19 trials.

**How to read it:**

- Compare any Sharpe with this, not with zero.

**What it does not tell you:** A guarantee that a Sharpe above it is real.

**Traps:**

- σ_SR is assumed at 1.0, not measured (A-021). At 0.5 the same bar is 0.94; at 1.5 it is 2.82. The page marks it 'assumed' until five distinct subjects exist.

**Related:**

- [trial-count](../validation/trial-count.md)
- [deflated-sharpe](../validation/deflated-sharpe.md)
- [sharpe-ratio](../performance/sharpe-ratio.md)

**Sources:**

- Bailey & López de Prado, The Deflated Sharpe Ratio: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf (research 015).

## Example answers

**Q:** My strategy has Sharpe 1.5. Beats the bar?

**A:** Not at 19 trials, where the bar is 1.88 with the assumed spread. Noise alone would be expected to produce a best result of about 1.88.
