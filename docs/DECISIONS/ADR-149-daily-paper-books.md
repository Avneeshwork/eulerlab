# ADR-149 — Paper books for H-0168 and H-0162, and delivery charges in the study replay

**Context.** Operator, 2026-11-07: "build it", for paper books for H-0168 (results-morning gap fade, same day) and H-0162 (promoter buys held 20 sessions). The Deploy button said "unknown shape 'daily_cash'": only `rule_book` rules can paper-trade, and `study_book.replay` charged every fill at intraday rates and expected every trade to open and close on one day.

**Options.** A new multi-day engine; or generators in `rule_book` plus a per-trade `segment` in the replay, with a multi-day hold booked on its exit day.

**Choice.** `deploy/daily_books.py`: H-0168 lands NSE's results announcements one finished day at a time (`nse_earnings_announcements.land(d, d)`), dates each by dissemination time, and fades a 3% gap open to close with H-0161's shortability checks; H-0162 reads SAST after the holdout end and returns each closed 20-session hold as one trade on its exit day with `segment: delivery`. `study_book.replay` charges `delivery` trades at delivery rates.

**Why.** It reuses the OMS, kill switch, recovery and state file every paper book uses, and keeps the gated rule's code path.

**Cost if wrong.** H-0162's open positions are invisible until they close and its equity curve steps on exit days, so drawdowns inside a hold are not shown; the backtest dated results by filing time, the book by dissemination time (a few minutes later at most); both books cover at the official close, which an MIS position cannot reach.
