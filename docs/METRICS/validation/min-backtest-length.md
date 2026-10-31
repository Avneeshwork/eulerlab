# Minimum backtest length (MinBTL)

*Family: Validation and the gate. Id: `min-backtest-length`.*

**In one line:** Years of history needed before a target Sharpe can be told apart from luck, given N trials.

**Where you see it:** Gate; `min_backtest_length_ratio`.

**How we compute it:** (SR₀ / SR_target)² years (`validation/statistics.min_backtest_length`; `docs/ARCHITECTURE.md` §5.5).

**Data and freshness:** Trial count.

**What is normal (our data, as of 2026-10-30):** The gate needs at least 1.5 times the required length (`mandate.yaml` (operator-owned)).

**How to read it:**

- If the needed length exceeds the history held, no analysis of that history can support the claim.

**What it does not tell you:** Quality of the data.

**Traps:**

- Grows with trials, like the noise bar.

**Related:**

- [noise-bar](../validation/noise-bar.md)

**Sources:**

- Bailey et al., Pseudo-mathematics and financial charlatanism (cited in `validation/statistics.py`); research 015.

## Example answers

**Q:** We have 10 years. Enough?

**A:** For a target Sharpe of 1 with the current noise bar, about (1.88/1)² ≈ 3.5 years are needed, and 1.5× that is 5.3, so 10 years passes this one check.
