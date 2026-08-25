# ADR-043 — A signal is swept on the market its paper tested

**Status:** ACCEPTED · 2026-08-25

**Context.** `make optimize` sweeps a strategy's parameters and reports the
best candidate beside the median. Its first version resolved the market with
two lines: crypto if the declared `recommended_class` contained "crypto",
otherwise NSE equity on `RELIANCE`.

That default swallowed ten of the twenty-one swept strategies. Nine cite
Mesfin (2026), whose tests run on **MNQ**, the Micro E-Mini Nasdaq 100 future.
One cites Zarattini, Barbon & Aziz, whose opening-range study covers roughly
**7,000 US equities**. All ten were being evaluated on a single Indian
large-cap, on a different exchange, in a different session, in a different
currency, under an Indian tax and fee schedule.

Nothing failed. Every one produced a plausible number with a plausible fill
count, and the sweep printed them in a tidy column. `orb_breakout` on
`RELIANCE` returned a best of +31,399 against a median of +4,011 — an eightfold
spread that reads as a signal with one lucky parameter. On QQQ, the index its
paper actually measures, the same sweep returns +25,582 against a median of
+19,532: a 1.3x spread, which is the shape of a parameter the result does not
much depend on. The wrong market did not produce an obviously wrong answer. It
produced a **differently shaped** one, and the shape is the whole finding.

**Options.**

1. **Sweep everything on what is loaded.** Free, and what the first version
   did. The objection is not that NSE data is bad but that the question
   changes: a signal published on a Nasdaq index future, evaluated on an Indian
   large-cap, is being asked whether it generalises, while the output is
   labelled as though it were being asked whether it replicates.
2. **Refuse to sweep anything without its exact instrument.** Honest and
   useless: this platform holds no futures data, so nine of the twenty would
   never run, and `orb_in_play` would need 7,000 symbols to run once.
3. **Map each strategy to the nearest instrument this platform holds, and say
   so in the mapping.** QQQ for the MNQ family, SPY for the US cross-section,
   BTCUSDT for crypto, RELIANCE only for what was actually tested on NSE.

**Choice.** Option 3, with the substitution written down rather than implied.
`market_for()` in `optimize_run` is the single place a strategy's declared
`recommended_class` becomes an instrument, and `futures -> us` carries a
comment saying what is being traded away: no roll, no overnight margin, no
futures tick, and a 6.5-hour cash session standing in for a nearly 23-hour
futures one. A-032 records the same thing where assumptions are audited.

The mapping deliberately lives above the loader. Putting `futures -> QQQ`
inside `candles_for` would make the substitution invisible at every call site,
which is how the `RELIANCE` default survived as long as it did.

**Consequences.**

Three things followed immediately, and none of them were the sweep itself.

*A US minute reader had to exist.* `candles_for` knew NSE and crypto only, so
the 71M US minute bars already landed from Alpaca were unreachable from any
backtest. `intraday/us_store.py` is the third source.

*The session had to be cut at the read.* Alpaca's bars run from roughly 08:00
to 16:53 New York. Every opening-range signal in the library defines its range
from the first bars of the session, so an unfiltered file makes an 08:01
pre-market print the "open". The filter belongs at the read, where every signal
inherits it, and is computed in `America/New_York` rather than as a fixed UTC
offset — 13:30-20:00 UTC is correct from March to November and an hour wrong
the rest of the year, which would silently drop the first hour of every winter
session and still return a number.

*A US cost model had to exist.* Without one, `asset_class="us"` fell through to
`Segment.EQUITY_INTRADAY` and a QQQ trade was charged **STT, SEBI turnover
fees, stamp duty and GST on brokerage**. This is precisely the error
`costs/delta_exchange.py` was written to fix, arriving from the opposite
direction, and it survived in the codebase for as long as nothing traded US
instruments. See A-029.

That last one changes how the crypto result should be read. The finding on
record is that all ten crypto signals lose on Bitcoin and that **88% of the
loss is Delta's fees** — 0.118% a round trip. The same round trip in US equity
costs about **0.002%**, roughly a fiftieth. A signal whose gross edge cannot
clear 0.118% may still clear 0.002%, so "these signals do not work" was never
the right reading of the crypto sweep; "these signals do not work *at Delta's
fee schedule*" was, and the US sweep is the first evidence able to separate
the two.

**What this does not fix.** QQQ is not MNQ, SPY is not 7,000 names, and IEX
volume is not consolidated volume — that last one directly undercuts the three
volume-keyed signals, all of which lost (A-031). The sweep is now asking a
nearer question than it was, not the paper's question.
