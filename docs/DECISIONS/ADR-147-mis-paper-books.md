# ADR-147 — Paper books for the MIS stock rules

**Context.** Operator, 2026-11-07, after research 168-170: "show all strategies their results potential demerit and go ahead", read as yes to building paper books for the five gated stock rules (H-0132 PROMOTE; H-0118, H-0121, H-0115, H-0124 PAPER). `rule_book` traded only the four rules of ADR-142.

**Options.** A new engine; a generator per rule written again; or generators that call the exact rule functions the gate judged.

**Choice.** `deploy/mis_book.py`: one generator per card that builds research 161's snapshots from minute files after the holdout end, builds the same `mft_screen.Market` (no beta, no industry: these five need neither), runs the gated rule function and the ten-open book, and returns `rule_book` trades. A position is half the deployment's capital in notional (₹5 lakh on ₹10 lakh of margin, 5x when ten are open). Registered in `rule_book.RULES`, so Deploy, the blocker and `study_book.run` need no change.

**Why.** The rule the book trades is the function the gate scored, so paper evidence is about the same rule.

**Cost if wrong.** Each run reads every F&O stock's minute files since the holdout end (slow, as T-4481). The ranking needs 20 sessions of history (H-0132: 21), so a book is empty for its first month. The OMS applies no margin check: a book can hold 5x its capital, which is the backtest, not a broker's live limit (A-117).

**Addendum, 2026-11-07.** H-0146 (research 171, PROMOTE at 1x) added: a position is a tenth of the capital (₹1 lakh on ₹10 lakh), `mis_book.SHARE`.
