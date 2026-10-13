# 078 — Two US stock rules on the 100 largest Indian stocks

**Question.** Operator, 2026-10-13: "add all paper to research library and
start coding and backtesting". Do the two rules research 077 chose, the
end-of-day reversal (H-0007) and the opening half-hour repeating (H-0008),
exist in large Indian stocks, and does either survive costs?

**Answer: neither exists here, before costs.** Both lose heavily after them.

## Sources

Read on 2026-10-13 for research 077, which records what was and was not read:
Baltussen, Da & Soebhag (2025), main sections of the PDF; Heston, Korajczyk &
Sadka (2010), through a summary of the full text. Nothing new was fetched for
this note.

## Rules as run

`make stock-intraday`. One-minute bars from Kite, 2021-08-20 to 2026-10-12,
1,265 sessions. The 100 largest companies with minute history, **chosen by
today's market value**, which is survivorship bias.

- **End-of-day reversal.** At 14:10 rank the stocks by their return since the
  previous session's last trade. Skip half an hour. At 14:40 buy the lowest
  group and short the highest; close at 15:10. Groups are fifths (the paper's
  main table) and tenths; both sides, and the losers alone. Four settings.
- **Opening half-hour repeats.** Rank on yesterday's return from the 09:16
  open to the 09:44 close. At 09:16 buy the top tenth and short the bottom;
  close at 09:45. One setting.

What differs from the papers:

- **The half-hour.** The reversal paper holds the last half-hour to the close.
  Stocks with derivatives are squared off at 15:12 (A-057), so this holds
  14:40 to 15:10. A different half-hour, chosen here before any result.
- **The previous close** is the last traded minute, not the official close.
- **The first print is never used** (research 075).
- A move of more than 20% is treated as a split or a bad print and not ranked.
- An exit waits at most two minutes for a trade; otherwise the day is skipped.

Costs: `costs.router` at NSE intraday rates plus 2 bps slippage a side
(A-056). ₹10 lakh, equal slots, half the equity on each side.

## Results

Before costs, in the papers' own measure (average spread a day):

| Rule | Spread, bps a day | t | The paper |
|---|---|---|---|
| Reversal, fifths, losers minus winners | 0.31 | 0.6 | 3.41 to 6.38 |
| Reversal, tenths, losers minus winners | -0.18 | -0.2 | larger than fifths |
| Reversal, fifths, losers alone | 4.08 | 6.2 | |
| Reversal, tenths, losers alone | 3.91 | 5.2 | |
| Opening half-hour, top minus bottom tenth | -0.66 | -0.5 | more than 11 |

After costs:

| Rule | Trades | Gross Sharpe | Net Sharpe | Net return | Net bps a trade |
|---|---|---|---|---|---|
| Reversal, fifths, both sides | 43,603 | 0.27 | -21.40 | -77.0% | -14.7 |
| Reversal, fifths, losers alone | 22,550 | 2.78 | -5.95 | -66.2% | -9.9 |
| Reversal, tenths, both sides | 21,827 | -0.11 | -14.99 | -78.6% | -15.2 |
| Reversal, tenths, losers alone | 11,033 | 2.33 | -4.92 | -64.8% | -9.3 |
| Opening half-hour repeats | 21,744 | -0.21 | -8.12 | -79.0% | -15.5 |

Every setting is in `data/derived/stock_intraday_papers.json`.

## The losers' gain is not a reversal

The losers alone gain about 4 bps a day with a t of 6, which looks like the
paper's finding. It is not. Measured directly on the same days:

| Stocks, 14:40 to 15:10 | bps a day | t |
|---|---|---|
| All 100 | 3.77 | 6.1 |
| Lowest fifth (the day's losers) | 4.66 | 6.3 |
| Middle three fifths | 3.33 | 5.4 |
| Highest fifth (the day's winners) | 4.28 | 6.1 |
| Losers minus all | 0.89 | 2.6 |
| Winners minus all | 0.51 | 1.5 |

**Every large stock rises in that half-hour**, winners as much as losers. The
long-only result is the market's own drift from 14:40 to 15:10, bought twenty
stocks at a time. The cross-sectional effect the paper describes, losers up
and winners flat, is 0.9 bps for the losers and has the wrong sign for the
winners.

By year the drift was 2.1, 3.7, 6.5, 4.4 and 4.3 bps a day from 2021 to 2025
and -0.3 in 2026 (191 sessions).

## Findings

1. **No end-of-day reversal in large Indian stocks**, in the half-hour that
   can be traded. Losers minus winners is zero in fifths and tenths.
2. **No same-time continuation at the open.** The spread has the wrong sign.
3. **A market-wide rise from 14:40 to 15:10**, 3.8 bps a day, t 6.1, found
   while checking finding 1. It was not a hypothesis and was not looked for,
   so its t-statistic overstates it. It is below the 6 bps a round trip costs
   in NIFTYBEES, and it is absent in 2026.
4. **Costs were about 15 bps a round trip**, not the 9 of research 076: with
   ₹10 lakh over 20 or 40 slots a position is ₹25,000 to ₹50,000, and fixed
   charges weigh more on a small order. A bigger account would pay less; no
   result here turns on it, because the spreads are zero before costs.

## Decision

H-0007 and H-0008 are rejected at screening. Neither goes to the gate. No
trial was recorded: five published settings, nothing searched. Both are in
the strategy library as studies and linked from their papers.

**Confidence:** high that neither spread exists in these 100 stocks over
these five years. Lower on what that says about the papers: the reversal was
tested on a different half-hour from the one published, and the universe is
100 survivors, where the paper finds its effect weakest in the largest firms
and strongest in the smallest.

## Open

- The 14:40 to 15:10 drift is a new observation, not a result. Testing it on
  the index future would be a new hypothesis with its own trial, and research
  071 and 076 already found nothing tradable in the last half-hour of the ETF.
- The reversal in smaller stocks, where the paper finds it four times
  stronger. Minute history is held for about 420 symbols; costs and slippage
  would be worse there.
