# Data grade (A to D)

*Family: Data quality. Id: `data-grade`.*

**In one line:** How far a dataset passes the quality contract: registered, provenance, fingerprint, sense, quarantine.

**Where you see it:** Data Status; brief Data line; `data/quality/grades.json`.

**How we compute it:** A all checks pass; B warnings only; C one failure; D more, or nothing landed. A derived table takes the worst grade of its inputs; a source that cannot date its values is B at best (`quality/contract.py`; ADR-086).

**Data and freshness:** `make data-quality`.

**What is normal (our data, as of 2026-10-30):** On 2026-10-31, 24 of 42 sources were C or D.

**How to read it:**

- C or D under a figure means check that figure before trusting it.
- `make backtest` refuses a price panel below its minimum grade unless overridden.

**What it does not tell you:** Freshness (reported beside the grade).

**Traps:**

- Many sources are C for provenance gaps (licence unreviewed), not wrong numbers (S-044).

**Related:**

- [freshness](../quality/freshness.md)
- [point-in-time](../quality/point-in-time.md)

**Sources:**

- `docs/ARCHITECTURE.md`, The data quality contract (ADR-086); research 011, 012.

## Example answers

**Q:** Price panel is grade C. Can I trust the backtest?

**A:** Grade C means one check failed. Open Data Status to see which: a provenance gap does not change numbers, a sense failure might.
