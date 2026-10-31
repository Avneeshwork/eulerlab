# Company P/E and industry median P/E

*Family: Company fundamentals. Id: `company-pe`.*

**In one line:** Price over trailing earnings per share, against the median of profitable peers.

**Where you see it:** Company page header.

**How we compute it:** Trailing EPS = sum of the last four quarters, only when all four exist. Industry median P/E = median over companies in the same industry with positive earnings, blank below three (`docs/ARCHITECTURE.md`, Company pages (ADR-065)).

**Data and freshness:** screener.in fundamentals (not point in time, A-066).

**What is normal (our data, as of 2026-10-30):** Compare with the industry median, not the market.

**How to read it:**

- Far above peers: the market expects faster growth, or it is expensive.

**What it does not tell you:** Value on its own; a low P/E can mean falling earnings ahead.

**Traps:**

- Loss-making companies have no meaningful P/E.
- One-off gains inflate EPS.

**Related:**

- [valuation](../market/valuation.md)
- [returns-on-capital](../fundamentals/returns-on-capital.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Company pages (ADR-065)

## Example answers

**Q:** P/E 45 vs industry 28?

**A:** Investors pay much more per rupee of earnings than for peers; that needs faster growth to be justified.
