# ADR-145 — Index-option straddles and index-futures rules in the intraday battery

**Context.** Operator, 2026-11-07: five day-trading strategies that pass the gate, Indian markets only, then "keep 1st strategy only" (the BankNifty expiry-day straddle) and research stock trading. The battery (ADR-139) read only `cs.Trade` stock trades; a straddle has no share quantity and a future is sized in continuous units.

**Options.** (a) Wrap straddles and futures as fake stock trades; (b) a protocol of the four fields the battery reads (symbol, day, gross, costs); (c) a separate battery per instrument.

**Choice.** (b): `validation.intraday.DayTrade`. `options/index_expiry_screen.py` (H-0041, H-0103 to H-0105) and `intraday/index_futures_screen.py` (H-0099 to H-0102) return their own trades through it. Only H-0103 was gated, on the operator's choice: PROMOTE (ledger #96, #97). The futures rules use index minutes as the future's price (A-115). `gates.py` and `mandate.yaml` are unchanged.

**Why.** The battery's statistics need daily net returns and per-symbol P&L, nothing else; one protocol keeps one battery.

**Cost if wrong.** A straddle's "drop best 5 names" stress removes the only underlying and reads 0% kept; simple mode does not check it, strict mode would. H-0103's fills are bhavcopy opens, never checked against minute option prices, and BankNifty has had only monthly expiries since 2024-11-20.
