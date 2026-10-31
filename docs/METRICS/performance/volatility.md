# Volatility (annualised)

*Family: Strategy performance. Id: `volatility`.*

**In one line:** Standard deviation of daily returns scaled to a year.

**Where you see it:** Reports; `volatility`.

**How we compute it:** √(sample variance × 252) (`src/eulerlab/reports.py` (`_figures`)).

**Data and freshness:** Daily returns.

**What is normal (our data, as of 2026-10-30):** India VIX's long-run median of about 15 is a reference for the index's own implied level.

**How to read it:**

- Divide by √252 for a typical daily swing.

**What it does not tell you:** The size of the worst days (see skew and kurtosis).

**Traps:**

- Includes flat days; a strategy mostly in cash shows low volatility.

**Related:**

- [sharpe-ratio](../performance/sharpe-ratio.md)
- [skew-and-kurtosis](../performance/skew-and-kurtosis.md)

**Sources:**

- `src/eulerlab/reports.py` (`_figures`)

## Example answers

**Q:** Volatility 18%?

**A:** A typical day moves about 1.1% (18 / 15.9). Bad days are bigger: check the worst day and kurtosis.
