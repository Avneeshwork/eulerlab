# ADR-148 — A paper book for H-0161 that shorts only stocks a broker would let it short

**Context.** Operator, 2026-11-07: "build it", for the ASM/T2T check and H-0161's paper book. H-0161 (research 173) shorts small, speculative NSE stocks intraday; many such stocks are trade-for-trade (series BE/BZ) or on NSE's ASM/GSM lists, where intraday trading is barred or brokers block MIS. The backtest could not see this (A-120).

**Options.** Ignore it; filter by today's lists only; filter by the lists as of the previous evening and refuse days with no list.

**Choice.** `deploy/delivery_fade_book.py`, registered in `rule_book.RULES`: the gated rule on daily bars after the holdout end, skipping a stock in series BE/BZ in the previous session's bhavcopy (`ingest/trade_for_trade`, history from 2015) or on the ASM/GSM snapshot landed on or before the previous session (`nse_reports` `asm`, `gsm`, `sec_list`, landing nightly from 2026-11-07). A day with no snapshot on or before it is not traded. Covers at the official close (variant, stated in the book's state).

**Why.** The lists that bar a short are known the evening before; using them then adds nothing from the trade day, and refusing days without a list keeps the book from shorting what it could not.

**Cost if wrong.** The book trades nothing before 2026-11-08 (no ASM snapshot earlier) and nothing for its first 20 sessions of post-holdout data; the close is not the 15:12 square-off price; Zerodha's own MIS block list is wider than NSE's and is not read.
