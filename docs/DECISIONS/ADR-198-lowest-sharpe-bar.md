# ADR-198 — The gate's Sharpe bar at its floor: net Sharpe above zero

**Context.** Operator, 2026-11-15: "make sharpe bar to minimum and rebacktest every strategy". Decision card answer: "Sharpe above zero, keep checks".
**Options.** (a) PSR floor 0.50 for promote and paper, other simple-mode checks kept; (b) Sharpe > 0 with every other check off; (c) leave the mandate and only rank.
**Choice.** (a). `mandate.yaml` `simple.min_probabilistic_sharpe` 0.95 → 0.50 and `paper.min_probabilistic_sharpe` 0.80 → 0.50. A PSR of 0.50 is the same test as a net Sharpe above zero. Still required: positive overall, in each half, at 2x costs, and in 60% of years. Strict mode is unchanged.
**Why.** Below zero a strategy loses money after costs; the other checks are cheap protection against a result that only works on paper.
**Cost if wrong.** More PROMOTEs that are noise: a Sharpe of 0.3 over ten years is not distinguishable from luck once 250 cards have been tried. Paper trading is the filter now, not the gate. Restore 0.95 / 0.80 to undo.
