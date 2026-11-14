# ADR-189 — 2000-2014 rows in a research-only history file; an optional research start

**Date:** 2026-11-14. **Status:** accepted. T-4611.

- **Context.** The rebuilt 2000-2014 rows (ADR-187, ADR-188) would take `price_panel.jsonl` from 5.48M to about 9.6M rows. The API and the paper runner load the whole panel; on this 8 GB Mac that is about 1.7 GB becoming about 3 GB in each. The rebuilt factor files also carried 90 newer factors (Aug-Sep 2026 ex-dates) that would change what the paper books replay.
- **Options.** (a) Append everything to `price_panel.jsonl`. (b) Keep 2000-2014 in `price_panel_2000_2014.jsonl` with its mask, read only by research, and add only confirmed pre-2015 rows to the factor files.
- **Choice.** (b). `features/panel_mask.HISTORY_PATH` and `MASK_PATH` name the two files. `daily_universe_screen.load_panel`, which `daily_more_screen` and the rule engine use, reads the history file only when its window starts before 2015, and leaves out rows the bhavcopy checks proved wrong. `vector.run` never fills or marks at a proved-wrong row; decisions still see it through `MarketView` until it was knowable. `constitution.Periods.research_start` is optional and defaults to 2016-01-01, so the research window moves only when the operator writes the line. The 90 newer factors wait for their own decision (T-4614).
- **Why.** Every live process loads exactly what it did, and the paper books cannot change: every factor row from 2015 on is byte-identical to the previous file.
- **Cost if wrong.** Research before 2015 cannot run until the cost schedule covers those years (it starts 2015 and refuses earlier trades, T-4613). Readers other than these do not see the history file.
