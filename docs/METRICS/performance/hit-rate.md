# Hit rate (daily) and win rate (per trade)

*Family: Strategy performance. Id: `hit-rate`.*

**In one line:** Share of up days, or share of closed trades that made money.

**Where you see it:** Reports (`hit_rate`, `hit_rate_invested`); trade tables (`win_rate`).

**How we compute it:** Daily: up days / all days, and up days / invested days (`src/eulerlab/reports.py` (`_figures`)). Per trade: closed trades with net > 0 / closed trades (`trades.summary`).

**Data and freshness:** Daily returns; closed trades.

**What is normal (our data, as of 2026-10-30):** No fixed level: a low win rate with large winners can be profitable.

**How to read it:**

- Meaningless without the size of wins and losses: read with average gain and loss, or profit factor.

**What it does not tell you:** Profitability.

**Traps:**

- The plain daily hit rate counts flat days as misses; use the invested version.

**Related:**

- [profit-factor](../performance/profit-factor.md)

**Sources:**

- `src/eulerlab/reports.py` (`_figures`)
- `src/eulerlab/trades.py`.

## Example answers

**Q:** Win rate 38%. Broken?

**A:** Not by itself. If winners average three times the losers, 38% is profitable. Check the profit factor.
