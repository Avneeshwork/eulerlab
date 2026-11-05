# 075 — Does the opening range read an ETF's first print as a price?

**Question (T-4040).** Research 071 found NIFTYBEES's 09:15 print is on average
71 bps away from the first minute's close. `intraday/papers.opening_range_breakout`
and its relatives take the opening range from the first bars' highs and lows,
first bar included. On an ETF, is that range a range or an artefact?

## Source

Our own Kite minute archive, read through `intraday.store.fetch`. No web source.
Measured 2026-10-12 on the last 500 full sessions of each symbol. No strategy
was run and no trial was spent: this measures the bars, not a rule.

## Measured

The 15-minute opening range, as a share of price, with and without the first
one-minute bar:

| Symbol | Kind | Median range with the first bar | Without it | Days the first bar sets the high or low |
|---|---|---|---|---|
| NIFTYBEES | ETF | 72.7 bps | 25.2 bps | 99.6% |
| GOLDBEES | ETF | 98.5 bps | 19.4 bps | 99.6% |
| RELIANCE | share | 72.0 bps | 52.2 bps | 88.2% |
| HDFCBANK | share | 75.1 bps | 51.9 bps | 89.2% |
| TCS | share | 99.3 bps | 71.7 bps | 88.4% |

BANKBEES had no full sessions in the archive.

## Findings

1. **On the two ETFs the first bar is the opening range.** It sets an edge on
   all but two days in 500 and makes the range three to five times as wide as
   the fourteen minutes after it.
2. **On shares the first bar also usually sets an edge**, and widens the range
   by about 40%. That is what an opening auction does to a share and is not
   evidence of a bad print. Whether it is a fair breakout level is a separate
   question this does not answer.
3. So an opening-range rule on an ETF asks for a break of a level set by a
   print research 071 showed is not a price. A long breakout needs a move
   several times the session's real early range before it fires.

## Which stored results this touches

Three, all on NIFTYBEES, all already negative and none adopted:
`orb_breakout_in` (Sharpe -3.83), `orb_in_play_in` (-1.73) and
`gap_continuation_in` (-3.68). They are results about the first print, not
about opening-range breakouts on the index. `ou_reversion_in` on NIFTYBEES
(the adopted one) does not build an opening range and is not touched.

## Decision

Nothing is re-run. The three failed and a failed strategy is dead (`CLAUDE.md`);
"the same rule without the first bar" is a new configuration and a new trial,
to be proposed as a hypothesis if wanted, not slipped in as a fix. HISTORY #20
records that the three numbers do not mean what their names say.

## Confidence

High on the measurement. Not measured: other ETFs, or whether dropping the
first bar would help.

## Open

- Should `opening_range_breakout` refuse an ETF, or start its range at the
  second bar for one? A change to a coded rule; needs its own hypothesis.

**Addendum, 2026-11-06 (research 159, H-0071).** The same holds for the daily
bars: NIFTYBEES's daily open in `price_panel.jsonl` is often a bad first print
(2020-03-05 "opened" at 142.95 and closed at 119.75). Its daily open-to-close
differs from the Nifty's by a median 43 bps a day (199 bps in 2021), so a
daily-bar NIFTYBEES trade must use the index's open and close instead.
