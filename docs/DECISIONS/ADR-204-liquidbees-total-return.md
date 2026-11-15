# ADR-204 — LIQUIDBEES as a total-return series in research runs

**Context.** HISTORY #97: LIQUIDBEES' price is flat at ₹1,000 because it pays daily dividends as units, so every backtest's cash leg earned 0%. Operator, 2026-11-15: "yeah fix liquidbees".
**Options.** (a) Factor-store dividend events (affects every reader, paper and live included); (b) a total-return price series in the research reader; (c) leave it.
**Choice.** (b). `features.panel.with_cash_yield` prices LIQUIDBEES as ₹1,000 grown by IIMA's daily 91-day T-bill return less 0.69% a year (research 197, A-157). The portfolio cards' source (ADR-203) applies it.
**Why.** No primary daily dividend record was fetchable; the T-bill proxy is from RBI via IIMA and already landed. Paper and live books are untouched, so no replay changes.
**Cost if wrong.** The cash leg's return is the 91-day T-bill's, not the overnight rate's: off by up to about 1% a year in stress years. The TER is one number for 22 years.
