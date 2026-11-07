# 176 — Ten more rules on every liquid NSE stock, daily bars: five intraday, five swing

**Question.** Operator, 2026-11-07: "start researching of more strategies",
under the standing scope (NSE cash stocks, 1x, half intraday, half swing,
other data as signals).

**Status.** H-0164 to H-0173 pre-registered and committed before any run.
Results follow under "Results".

## Set-up

Research 173's frame, the one that survived HISTORY #82: daily bars of the
500 most traded NSE stocks each day, stocks in series BE/BZ the previous
session skipped (research 174). Intraday = official open to official close,
cash intraday costs, ₹1 lakh, ten a day. Swing = delivery, long only,
₹1 lakh, ten open. Screen as research 170.

| Card | Kind | Signal |
|---|---|---|
| H-0164 | intraday | 3% fall on half the usual delivery: buy (H-0161's mirror) |
| H-0165 | intraday | 3% rise on twice the usual delivery: buy |
| H-0166 | intraday | one-sided bulk buying: buy next day |
| H-0167 | intraday | one-sided bulk selling: short next day |
| H-0168 | intraday | results-morning 3% gap: fade |
| H-0169 | swing, 10 days | one-sided bulk buying |
| H-0170 | swing, 10 days | 3% rise on twice the usual delivery |
| H-0171 | swing, 5 days | 3% fall on half the usual delivery |
| H-0172 | swing, 20 days | results gap up 3% with 1.5x delivery |
| H-0173 | swing, 20 days | new 250-session high on twice the usual delivery |

H-0164 and H-0171 were written as mirrors of H-0161 after it passed, and say
so. Bulk deals and results dates start 2021-07; the rest run 2016-2024.

## Results

Screen 2026-11-07 (`make daily-more`), then the gate for the one that passed.
Bps a trade or position, net of costs.

| Card | Count | Gross | Net | Net Sharpe | Halves | At 2x costs | Verdict |
|---|---|---|---|---|---|---|---|
| H-0164 | 1547 | -30.87 | -43.12 | -1.08 | -1.218 / -0.941 | -1.383 | screen fail |
| H-0165 | 427 | -68.28 | -80.51 | -1.356 | -0.543 / -2.688 | -1.551 | screen fail |
| H-0166 | 337 | -27.17 | -39.41 | -1.039 | -1.573 / -0.586 | -1.352 | screen fail |
| H-0167 | 705 | 16.72 | 4.47 | 0.185 | -0.59 / 0.788 | -0.329 | screen fail |
| H-0168 | 1,077 | 60.36 | 48.09 | 1.911 | 0.733 / 2.795 | 1.438 | **PROMOTE** |
| H-0169 | 291 |  | -60.02 | -0.41 | -0.934 / -0.045 | -0.588 | screen fail |
| H-0170 | 339 |  | 25.4 | 0.12 | 0.973 / -1.111 | 0.0 | screen fail |
| H-0171 | 1350 |  | -132.21 | -1.217 | -1.757 / -0.416 | -1.455 | screen fail |
| H-0172 | 0 |  | None | None | None / None | None | no events |
| H-0173 | 101 |  | -33.49 | -0.068 | 0.43 / -0.608 | -0.123 | screen fail |

1. **H-0168 PROMOTE (ledger #124, #125, after a bug fix)**: fading a 3%
   results-morning gap from the open to the close earns +48 bps net a trade
   on 1,077 trades over 2021-07 to 2024-11, every year positive, 0.95 Sharpe
   at 3x costs, 78% kept without the best five names. On F&O stocks with
   minute fills the same idea made 6.5 bps gross (H-0040): as with H-0161, the
   edge is in the smaller stocks. The first run (ledger #122, #123: 176 trades,
   +90 bps) skipped every disclosure made after the close, which is most of
   them (HISTORY #84); its PROMOTE is superseded.
2. **Delivery-ratio rules other than H-0161 lose**: buying low-delivery falls
   (-43 bps intraday, -132 over five days) and high-delivery rises (-81
   intraday). The fade of thin rallies is the only side that works.
3. **Bulk deals have no next-day edge on every liquid stock either**: buys
   lose (-39 intraday, -60 over ten days); shorting after sells makes +4.5,
   negative at 2x costs.
4. **H-0172 had no events**, before and after the fix. Delivery percentage falls on results reaction
   days (volume rises faster than delivery), so the 1.5x condition never met
   a 3% gap up with an up close (0 of 99). A design error, recorded, not fixed.
