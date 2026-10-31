# Overnight gap rule VaR

*Family: Risk on the live book. Id: `overnight-gap-var`.*

**In one line:** Risk of a position held only overnight, from past morning gaps on nights it would have held.

**Where you see it:** Live & Risk (futures deployment).

**How we compute it:** pnl(t) = N × g(t) on nights in position; VaR over those nights only, with at least 30 (`risk/book.rule_pnl`, `gap_summary`; ADR-072).

**Data and freshness:** Index opens and closes.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Read the 'on a night it holds' figure, not the book average.

**What it does not tell you:** Intraday risk.

**Traps:**

- Few signal nights: noisy.

**Related:**

- [value-at-risk](../risk/value-at-risk.md)

**Sources:**

- `docs/ARCHITECTURE.md`, A position held only overnight (ADR-072).

## Example answers

**Q:** Why two VaR figures for the futures book?

**A:** One averages quiet and signal nights; the other is only nights it actually holds, which is the risk you take when it trades.
