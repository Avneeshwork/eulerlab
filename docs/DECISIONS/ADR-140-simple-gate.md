# ADR-140 — The gate's simple mode

**Context.** Operator, 2026-11-06, after H-0096 was killed (deflated Sharpe 0.78, Romano-Wolf, concentration): "gate is too hard, make it simple, so many other strategies pass with positive returns". Offered a targeted fix, a moderate loosening, a simple gate, or paper trading as the decider; the operator chose the simple gate.

**Options.** Targeted (Romano-Wolf at own beta); moderate (plus DSR 0.90, concentration 50%); simple; keep the gate and decide by paper.

**Choice.** `mandate.yaml` gains `mode: simple` (version 2). In simple mode the gate checks: full-sample net Sharpe > 0, each half of the history net positive, still positive at 2x costs, and, added the same day on the operator's request for "other metrics, if the backtest is really profitable, like probabilistic Sharpe, stable": probabilistic Sharpe ratio >= 0.95 (Bailey and López de Prado; not corrected for the number of trials) and net positive in at least 60% of calendar years with 60+ sessions (`gates._check_simple`; `make validate` now writes each configuration's PSR and the best one's yearly results). The process rules (pre-registration, signed evidence, intact ledger, holdout read once) apply in both modes. The strict thresholds are kept unchanged under `statistical` and `robustness`; `mode: strict` restores them.

**Why.** The operator owns the mandate and chose it with the trade-off stated.

**Cost if wrong.** The simple bar does not correct for how much has been searched (about 100 hypotheses, 140 strategies), so strategies that are positive by chance will pass; `make gate-acceptance` still tests the strict bar and so no longer tests the gate in use. Forward paper trading is then the only check before money.
