# Concentration and sector share

*Family: Risk on the live book. Id: `concentration`.*

**In one line:** How much of the money sits in the largest names and the largest sector.

**Where you see it:** Live & Risk; Risk watch levels.

**How we compute it:** Shares of invested value by name and by sector (`risk/report.py`).

**Data and freshness:** Holdings.

**What is normal (our data, as of 2026-10-30):** Watch levels in `config/risk_watch.yaml` (operator-owned, proposed).

**How to read it:**

- One sector above the watch level is the first thing to check after a bad sector day.

**What it does not tell you:** Correlation between sectors.

**Traps:**

- Sector labels are today's (A-061).

**Related:**

- [component-var](../risk/component-var.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Risk on the deployed book (ADR-071)

## Example answers

**Q:** Largest sector 45%?

**A:** Nearly half the money rides on one sector; a bad day there dominates the book.
