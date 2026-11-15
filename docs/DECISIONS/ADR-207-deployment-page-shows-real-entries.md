# ADR-207 — The Deployment page shows only real entries

**Context.** Operator, 2026-11-16: clean the Live → Deployment page and remove what is not real. It showed 13 paper cards (7 stopped or halted, most never traded), 86 "passed the gate" rows (19 with no stored report, 17 paper cannot run) and long notes on every card.
**Options.** (a) Delete stopped deployments and unreported cards; (b) hide them behind a toggle, decided from data the page already has; (c) leave it.
**Choice.** (b). Full cards only for active books; stopped and halted books fold into one line each under "Show N stopped or halted". A gate row shows by default only if it has a stored report (`table.period` set) and no `deploy_blocker`, best 15 by Sharpe (realistic fills where the server has it, ADR-205); "Show all" lists every row with why it is not ready. Card warnings show their first sentence, the rest on hover. Operator, same day: each paper book links to its strategy's backtest report, showing its Sharpe and annual return; add/withdraw folds behind a button; the real-money panel is one header, one input row and one action row.
**Why.** Nothing is deleted, and a strategy whose report lands later (the factor cards being rebacktested) appears without another change.
**Cost if wrong.** A useful row ranked 16th or lower is one click away rather than on screen.
