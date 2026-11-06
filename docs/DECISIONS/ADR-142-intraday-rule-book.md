# ADR-142 — Paper books for the gated intraday rules

**Context.** Operator, 2026-11-06: build paper trading for H-0096, H-0098, H-0065 and H-0052, which the gate passed (PROMOTE or PAPER) but `forward.build` cannot trade: it builds only daily rank-and-hold cards, and `intraday_book` only one-symbol long brackets.

**Options.** A new engine; extend `intraday_book`; or generators that feed `study_book.run`, which already sends multi-symbol, two-sided intraday trades through the OMS.

**Choice.** `deploy/rule_book.py`: one generator per hypothesis, re-applying the gated rule to minute files after the holdout end, returning `study_book`'s trade shape. `study_book.run` gained `block=` so the book's own check (gate verdict PROMOTE or PAPER, holdout end set) replaces the study check. Routed in `runner.paper_blocker`, `runner.run`, the deploy preview and create routes, and `version_lock.sources`. Operator's choices on the plan: H-0098 runs as a variant (09:15 auction print in, out at 15:10, because an intraday short cannot reach the closing auction; 15:15 was planned, but these stocks' minute data ends at 15:14); H-0065 at its natural size (capital spread over about 80 positions a day).

**Why.** The order path, kill switch, recovery, history-change halt and state file are the ones every paper book already uses; only the trades are new.

**Cost if wrong.** A generator that differs from its backtest would make paper evidence about a different rule. Each mirrors its research function (tests pin the entry, exit, ranking and sizing) and the version lock flags any later change to it.
