# Your books in this kind of market

*Family: Strategy performance. Id: `books-in-this-market`.*

**In one line:** How each running book's own backtest did on the session after past days that looked like today.

**Where you see it:** Market brief, section Your books in this kind of market; `data.brief.books_history`.

**How we compute it:** For each active book, its strategy's longest stored backtest (`data/workspaces/<ws>/reports/<strategy>/`), the daily return on the session after each matching day from What history says; median and share up, with the count (`agents/history_says.books_in_this_market`).

**Data and freshness:** Stored backtest equity curves.

**Do we hold it:** Yes for every book with a stored report; a book without one is named.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Shows whether a book has tended to do better or worse than usual in this kind of market, in its own backtest.

**What it does not tell you:** Live results, or how the book will do now.

**Traps:**

- A backtest is not live trading: costs and fills differ.
- Under 30 days the brief says too few.
- Two deployments of one strategy share one backtest, so it is listed once.

**Related:**

- [history-base-rates](../market/history-base-rates.md)
- [sharpe-ratio](../performance/sharpe-ratio.md)

**Sources:**

- ADR-106.

## Example answers

**Q:** Which book suits this market?

**A:** In their own backtests, after days like today, india_sharpe_momentum_opt's next session had a median of +0.60% and was up 57% of the time over 116 days; nse_github_stocks_on_the_move's median was flat. That compares backtests, not live trading.
