# ADR-078: Paper trading for every strategy type, minute data forward of a frozen holdout

**Context.** Only daily target-weight strategies and the overnight Nifty future could paper-trade: 43 of 117. The operator asked (2026-10-17) that every type deploy. The other 74 run on minute bars (25 coded signals, 46 studies) or are option structures (2), and minute data after 2024-11-30 is the holdout, read once (`mandate.yaml`).

**Options.** Keep minute strategies off paper; spend the holdout read first; end the holdout on a fixed date and treat later minute data as forward paper evidence.

**Choice.** The operator chose to end the holdout on a fixed date (`forward_evidence: holdout_end` in `mandate.yaml`, operator-owned), and to build in stages: coded intraday signals (`deploy/intraday_book.py`), then studies, then option structures. One rule, `deploy.runner.paper_blocker`, decides what can deploy for the list, the preflight and the deploy route.

**Why.** Paper trading is how a strategy earns forward evidence; minute strategies could earn none. A fixed end keeps the holdout a holdout: nothing on or before it is read by a paper book, not even as warmup, and a deployment trades only from the day after it is made.

**Cost if wrong.** Minute data read after the end date is no longer unseen; if the operator later wants a longer holdout, the paper records of minute strategies overlap it and must be set aside from that evaluation.
