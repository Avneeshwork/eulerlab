# Time-weighted return (live and paper books)

*Family: Strategy performance. Id: `time-weighted-return`.*

**In one line:** Growth of the book with deposits and withdrawals taken out.

**Where you see it:** Live & Risk, paper cards, Telegram `pnl`, the brief's books.

**How we compute it:** index(t) = index(t−1) × equity(t) / (equity(t−1) + flow(t)) (`risk.book.growth`; `docs/ARCHITECTURE.md`, Risk on the deployed book).

**Data and freshness:** Deployment state: curve and flows.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- The right number for 'how did the strategy do'; rupees made answer 'how much money did I make'.

**What it does not tell you:** Rupees made.

**Traps:**

- Reading drawdown from raw equity counts a withdrawal as a loss (HISTORY #40).

**Related:**

- [max-drawdown](../performance/max-drawdown.md)
- [loss-limits](../risk/loss-limits.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Risk on the deployed book.

## Example answers

**Q:** The book shows equity down 20% but drawdown 3.7%?

**A:** ₹20,000 was withdrawn on 16 Oct. Equity fell by that amount; the strategy itself is 3.7% below its peak.
