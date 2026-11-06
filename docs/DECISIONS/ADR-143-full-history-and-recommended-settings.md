# ADR-143 — The gate's strategies over every year held, with their settings filled in

**Context.** Operator, 2026-11-06: "backtest all these strategies over all available timeframe" (the fifteen PROMOTE and PAPER hypotheses), "from 2016 to 2026", and "in backtest the recommended selection should already be filled up". Offered the pre-holdout window or the holdout too, stated that 2024-12 to 2026-10 is the project's single holdout read; the operator chose 2016 to 2026.

**Options.** Pre-holdout only; through the holdout end; through today.

**Choice.** `research/full_history.py` (`make full-history READ_HOLDOUT=<operator>`): daily cards from 2016 (a year of warm-up from 2015), intraday rules from the first minute bar (2021-08-20), H-0098 on daily bars from 2016, all to the holdout end (2026-10-17). Minute and daily data after it are the paper books' forward evidence and stay out. Each hypothesis's read is recorded in `holdout_reads.jsonl` before anything runs, and the cards' `holdout.status` becomes `read`. Every run is stored in the workspace result store with its setting; `RECOMMENDED` (start, end, universe, tier, asset class, timeframe, capital) is served as `recommended` on each fleet row, and opening the strategy in the library fills the backtest controls with it.

**Why.** The operator owns the holdout and chose to spend it, knowingly; recording the reads keeps that visible. Storing the runs means the library shows them without pressing Run.

**Cost if wrong.** No unseen data is left to test any of these strategies, or any later one, before money; forward paper trading is the only remaining out-of-sample evidence.
