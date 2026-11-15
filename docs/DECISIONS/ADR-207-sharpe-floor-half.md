# ADR-207 — A 0.5 floor on the gate's Sharpe for PROMOTE and PAPER

**Context.** Operator, 2026-11-15: "less than .5 sharpe should not be in paper", "in promote also set .5 sharpe as floor", then "Approve 0.5 Sharpe floor for PAPER and PROMOTE in gates.py and mandate.yaml, on the gate Sharpe".
**Options.** (a) Floor on the gate's full-sample net Sharpe; (b) floor on the realistic-fills Sharpe (ADR-205), which the gate cannot see; (c) no floor (ADR-198's PSR >= 0.50 only).
**Choice.** (a). `mandate.yaml`: `simple.min_full_sample_sharpe: 0.5` (read by `gates._check_simple`, zero when absent) and `paper.min_full_sample_sharpe` 0.0 -> 0.5. Every card from the 2026-11-15 rebacktest, the portfolio cards and the three factor passes are re-scored with `make gate` (no new backtest, one ledger entry each).
**Why.** The operator chose the gate Sharpe; it is the figure in every evidence pack.
**Cost if wrong.** A daily intraday card can clear 0.5 on official fills and still lose at realistic fills (H-0202: gate 12.75, realistic -0.32); the floor does not catch that. Changing the mandate trips the guardian halt; `make agents-resume` restarts the agents.
