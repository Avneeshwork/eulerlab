# ADR-141 — A PAPER verdict between PROMOTE and KILL

**Context.** Operator, 2026-11-06: "make gate less strict so that profitable strategies get a chance for paper trading and more evaluation instead of rejecting directly". The gate had two answers; anything short of PROMOTE was dead, so a profitable strategy with too little history never got forward evidence.

**Options.** Lower the promotion bar again; or add a third verdict that sends profitable strategies to paper trading without promoting them.

**Choice.** A third verdict, PAPER: promotion failed, but the process rules passed and the `paper:` bar in `mandate.yaml` passed (net full-sample Sharpe > 0, probabilistic Sharpe >= 0.80). PAPER allows a paper deployment (`forward.blocker`, `forward.paper_on`) and shows as stage `paper_candidate` / `paper_evaluation`; it never reads the holdout and never reaches the live preflight, which still needs PROMOTE. `make gate` exits 3 on PAPER. CLAUDE.md's rule now reads "a strategy the gate KILLs is dead".

**Why.** Forward paper trading is the evidence a short or marginal backtest lacks, and it costs no money. Keeping PROMOTE separate keeps the holdout and live money behind the full bar.

**Cost if wrong.** More strategies run on paper, so more paper books to watch; a PAPER strategy that does well on paper must still be re-gated before live.
