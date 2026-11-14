# ADR-188 — The old years' jumps: confirmed factors, and a dated mask MarketView applies

**Date:** 2026-11-14. **Status:** accepted for the copy in `data/derived/rebuild-2026-11-14/`; the live panel has no mask. A-146, research 195.

- **Context.** The 2000-2014 rows hold 3,280 one-day moves over 40%. Some are splits NSE wrote in older wording the parser missed, some misprints that revert next day, many unexplained (penny stocks in 2000-2001). Landing data cannot be edited, and a strategy must not trade on a misprint.
- **Options.** (a) Edit or drop rows in the panel. (b) Keep the panel as printed and publish a mask with `event_time` and `knowledge_time` that the reader applies by `as_of`.
- **Choice.** (b), `features/panel_mask.py`. The parser reads "Fv Split Rs.10/- To Rs.2/-" and its variants. Splits and bonuses of companies without an ISIN are keyed to their own id by resolving the symbol on the ex-date through the no-ISIN master. A pre-2015 price factor is kept only when the close-to-close ratio matches within 10%. A move that reverts within 15% next session excludes that row, known at the next close. Any other unexplained move excludes the instrument 20 sessions each side, known at the jump's close. 2000-2003 rows under Rs 10 are excluded. `MarketView.__post_init__` applies `data/derived/panel_mask.jsonl` when it exists.
- **Why.** The panel stays what the exchange printed, the mask is auditable line by line, and a decision before a jump still sees what was printed then.
- **Cost if wrong.** The thresholds are hand-chosen (A-146). The window before a jump is excluded only after the jump, so backtests standing before it are unaffected but later views lose those rows. Readers that bypass `MarketView` (the vector screens) do not apply the mask yet.
