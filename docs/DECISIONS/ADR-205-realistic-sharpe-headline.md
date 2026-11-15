# ADR-205 — The Strategies page leads with the Sharpe at realistic fills

**Context.** Operator, 2026-11-15: the page showed H-0202 at 12.75 and a 3.35 bar; "refresh all … else i will see these wrong ones" and, on the bar, "Use realistic Sharpes". Daily intraday cards fill at the official open and close (research 184), so their gate Sharpe is an upper bound: H-0202 is -0.32 at 09:25 → 15:10 with spread and impact.
**Options.** (a) Overwrite stored Sharpes; (b) a separate realistic figure per card, shown first, the official one beside it; (c) leave the page as it is.
**Choice.** (b). `research/realistic_sharpe.py` writes `data/derived/realistic_sharpe.json` (reprice `sharpe_executable` for daily intraday cards, the gate's Sharpe for the rest); the API attaches it as `realistic`; the list sorts and judges on it; KILL cards are off the default list. The page's luck bar shifts each repriced strategy's returns to its realistic Sharpe before measuring the families (A-158).
**Why.** Nothing the gate wrote is changed, and the inflated number stays visible with its window. The gate's own search correction (`assess`) is untouched.
**Cost if wrong.** The reprice covers only stocks with minute bars (about a third of H-0202's trades) and only 2018-11 to 2024-11, so a realistic figure can be noisy. The page bar and the gate's bar now differ, by design; the page says which it shows.
