# Recent-weighted (EWMA) VaR

*Family: Risk on the live book. Id: `ewma-var`.*

**In one line:** VaR from a volatility that weights recent days more, so it reacts faster.

**Where you see it:** Live & Risk VaR table.

**How we compute it:** sd² = Σ w_t pnl(t)² / Σ w_t, weights falling by 0.94 a day back; VaR = z × sd (`risk/book.recent_sd`; A-059).

**Data and freshness:** As VaR.

**What is normal (our data, as of 2026-10-30):** Above the plain VaR when the last weeks were rougher than the year.

**How to read it:**

- Use it to see whether risk is rising now.

**What it does not tell you:** Fat tails: it assumes a normal curve.

**Traps:**

- λ = 0.94 is RiskMetrics' daily choice, not fitted to Indian data (A-059).

**Related:**

- [value-at-risk](../risk/value-at-risk.md)

**Sources:**

- RiskMetrics Technical Document (1996), via secondary summaries; MSCI listing: https://www.msci.com/research-and-insights/paper/1996-riskmetrics-technical-document (2026-10-31).

## Example answers

**Q:** EWMA VaR above the plain VaR?

**A:** The last few weeks were more volatile than the past year on average; risk is rising now.
