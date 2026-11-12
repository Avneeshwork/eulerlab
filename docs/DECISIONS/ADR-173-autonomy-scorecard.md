# ADR-173 — The agents are scored on one page of outcomes, with the missing ones named

**Date:** 2026-11-13. **Status:** accepted. Issue #138 under #134.

- **Context.** The agents' output was counted as rules that pass a screen, which ten rules a night makes cheap (#131). The operator has no page that says what autonomy costs and what it has produced.
- **Options.** (a) A workbench screen; (b) a command that prints one page from stored records; (c) wait for forward results before showing anything.
- **Choice.** (b) first. `make scorecard` (`eulerlab/scorecard.py`): the month's spend on paid models against the budget and per agent, tests recorded and the families they form, the noise bar, the most searched families, the week's gate entries against the cap with verdicts, and paper books by status. "Strategies confirmed forward" and "operator minutes a week" print as not measured (T-4575).
- **Why.** A command is checkable today and needs no UI work while the server move is in flight; the API and the AI tab can read `build()` later. Naming the two missing numbers keeps the page from implying the agents have found an edge.
- **Cost if wrong.** If these are the wrong measures, the page is a hundred lines to change. The family count is quadratic in rules stored; at several thousand rules it will need a cache.
