# Profit factor and expectancy

*Family: Strategy performance. Id: `profit-factor`.*

**In one line:** Gross profit divided by gross loss over closed trades, and the average net per trade.

**Where you see it:** Trade tables; `profit_factor`, `expectancy`.

**How we compute it:** Sum of winning nets / −sum of losing nets; expectancy = mean net per closed trade (`trades.summary`).

**Data and freshness:** Closed trades, net of costs.

**What is normal (our data, as of 2026-10-30):** Above 1 means closed trades made money net of costs.

**How to read it:**

- With few trades it is very noisy.

**What it does not tell you:** Risk or drawdown.

**Traps:**

- Open trades are not scored.

**Related:**

- [hit-rate](../performance/hit-rate.md)

**Sources:**

- `src/eulerlab/trades.py`.

## Example answers

**Q:** (Illustrative) Profit factor 2.65 on 20 trades?

**A:** Promising but thin: a couple of trades either way would change it a lot.
