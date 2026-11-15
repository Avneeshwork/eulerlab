# ADR-199 — Library reports for any rebacktested card, cut at its holdout start

**Context.** Operator, 2026-11-15: "keep replacing with new report" after the ADR-198 rebacktest. `library_reports` stored seventeen fixed cards, and its trade sources now run to 2025-12-31 (ADR-184), past each card's holdout start, so a stored report would have shown holdout days.
**Options.** (a) Extend `library_reports`: any card id, `--from-results`, cut at `holdout.starts`; (b) a new module for the rebacktest; (c) delete old result rows so only the new one exists.
**Choice.** (a). Every trade, session and swing on or after the card's `holdout.starts` is dropped; a swing still open on that day is left out. The result log stays append-only; the library shows the latest run (`results.latest`), so the new report replaces the old one on screen.
**Why.** One module for stored reports; the holdout cut belongs where the report is built, not in each caller (the autopilot also calls `store_one`).
**Cost if wrong.** A swing open across the holdout start is missing from its report, so the last weeks before the holdout look slightly flatter than the gate's figures. Swing-card reports also rebuild the screen's data a second time (slower, no change to numbers).
