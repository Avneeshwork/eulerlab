# ADR-202 — Research runs of the 5x screens at 1x, opt-in

**Context.** Operator, 2026-11-15: "backtest at 1x only" (scope since 2026-11-07: 1x capital, no leverage). The MFT and quant screens (H-0111 to H-0140) were registered at Zerodha 5x MIS, ₹5 lakh a trade, ten open on ₹10 lakh; H-0163 was gated at ₹5 lakh a name. Every other daily and minute card is already ₹1 lakh a position, ten at most, on ₹10 lakh. `deploy/mis_book.py` uses the same constants.
**Options.** (a) Change `mft_screen.TRADE` to ₹1 lakh for everyone; (b) an opt-in switch, `EULERLAB_RESEARCH_1X=1`; (c) scale the 5x results by a fifth.
**Choice.** (b). With the switch, `mft_screen.TRADE` is ₹1 lakh and H-0163's validation run sizes ₹1 lakh a name. Fills and costs are computed at that size (brokerage has a flat part), not scaled.
**Why.** Changing the paper books' sizing would halt them (`HistoryChanged`); (c) gets costs wrong.
**Cost if wrong.** Two sizes of one card exist in the trial ledger; the 1x rows are what the operator sees (`ranking`, library), the 5x rows are marked superseded in the rebacktest log.
