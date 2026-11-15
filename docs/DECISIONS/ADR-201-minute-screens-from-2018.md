# ADR-201 — Minute screens can run from 2018-11, opt-in, research only

**Context.** Operator, 2026-11-15: "minute data is from 2018". The minute snapshots now carry Angel's rescaled history (T-4634), but the MFT, quant, onex and other-data screens start at `mft_screen.START` (2021-11-01) because Kite's Nifty minutes start there, and `deploy/mis_book.py` builds on the same module.
**Options.** (a) Move `START` to 2018-11-01 for everyone; (b) an opt-in switch, `EULERLAB_MINUTE_HISTORY=1`, that adds Angel's NIFTY50 minutes before 2021-11-01 and moves `START`; (c) leave 2021-11.
**Choice.** (b). `research_screen.minute_history()` reads the switch; `cash_five_screen.load_index` then puts Angel's NIFTY50 minutes (2018-11-01 to 2021-10-31; an index has no adjustment factor) before Kite's; `mft_screen.START` becomes 2018-11-01.
**Why.** Paper books replay from their start; moving their history underneath them would halt them (`HistoryChanged`). Research runs get the longer window by setting one variable.
**Cost if wrong.** Angel's index history ends 2021-09-15 and Kite's starts 2021-11-01, so 16 Sep to 29 Oct 2021 has no Nifty minutes and those sessions drop out of every screen that needs the index. Results with and without the switch are different configurations and each spends its own trials.
