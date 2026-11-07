# ADR-146 — Stock scalps sized at Zerodha MIS leverage

**Context.** Operator, 2026-11-07: "no option/ futures only stock scalping on leverage of 4-5x read from zerodha", for ten MFT-style rules at 5-10 trades a day. Earlier stock screens sized ₹1 lakh a trade at 1x, a 12.24 bps round trip.

**Options.** Keep ₹1 lakh at 1x; ₹1 lakh of margin at 5x (₹5 lakh a trade); a size per stock from its MIS margin.

**Choice.** ₹5 lakh a trade, at most ten open, returns on ₹10 lakh of margin (`intraday/mft_screen.py`, research 168). Round trip 8.46 bps: the ₹20 brokerage is per order, STT is unchanged. Earlier rules are not re-sized or re-gated.

**Why.** It is how the operator trades, and brokerage is the only cost leverage changes. Sharpe is unchanged by leverage; return and drawdown on margin are 5x.

**Cost if wrong.** Zerodha gives less than 5x on volatile stocks and can cut it intraday (A-117); slippage on ₹5 lakh is assumed, not measured, at 2 bps a side. Doubling every cost leaves H-0118 a Sharpe of 0.03; at 4 bps a side of slippage it keeps about +4.8 bps net a trade and H-0115 about +0.8.
