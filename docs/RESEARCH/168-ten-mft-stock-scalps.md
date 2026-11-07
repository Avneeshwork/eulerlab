# 168 — Ten MFT-style stock scalps on 5-minute bars, at Zerodha MIS size

**Question.** Operator, 2026-11-07: "after quant trading and MFT/HFT we have
to build strategies like them just instead of tick level we will first start
with minute level trades and take 5-10 trades a day ... research on such 10
strategies"; then "no option/ futures only stock scalping on leverage of 4-5x
read from zerodha".

**Status.** H-0111 to H-0120 pre-registered and committed before any run.
Results follow under "Results".

## Leverage and cost

Zerodha gives up to 5x on equity MIS ("5X (20% of the trade value based on
the volatility of the stock"), and the risk team can reduce it intraday
([bulletin](https://zerodha.com/marketintel/bulletin/249809/latest-intraday-leverages-mis-bo-co),
[support](https://support.zerodha.com/category/trading-and-markets/margin-leverage-and-product-and-order-types/articles/how-much-margins-leverage-does-zerodha-provide),
both fetched 2026-11-07). Auto square-off: 15:12 for stocks in the closing
auction, 15:25 for others; these rules are flat by 15:10.

Leverage does not change a rule's Sharpe; it changes the cost per rupee,
because brokerage is ₹20 an order however large:

| Notional a trade | Charges, round trip | With 2 bps slippage a side |
|---|---|---|
| ₹1 lakh (1x, earlier screens) | 8.24 bps | 12.24 bps |
| ₹5 lakh (₹1 lakh margin at 5x) | 4.46 bps | **8.46 bps** |

STT (2.5 bps on the sale) is most of what is left, and no broker removes it.
A member firm pays the same STT; its edge is the spread it earns, not lower
tax.

## The rules

Each card holds its rule in full. Common: the 100 most traded F&O stocks by
20-session traded value (50 for H-0119, 200 for H-0113 and H-0115), decided
on 5-minute closes, filled at the next minute's open, ₹5 lakh a trade, at
most ten open at once on ₹10 lakh of margin, flat by 15:10. Window
2021-11-01 to 2024-10-15 for all ten.

| Card | Idea | Source |
|---|---|---|
| H-0111 | Nifty burst, high-beta laggards | Lo and MacKinlay (1990); Hou (2007) |
| H-0112 | 30-minute residual reversal | Da, Liu and Schaumburg (2014) |
| H-0113 | Industry leader to laggard | Hou (2007) |
| H-0114 | Late-day momentum with the Nifty | Gao et al. (2018); Baltussen et al. (2021) |
| H-0115 | Gap fade after a 15-minute turn | practitioner |
| H-0116 | Opening drive with the Nifty | practitioner |
| H-0117 | Midday morning-range break | Crabel (1990), practitioner |
| H-0118 | Noon pullback on a trend day | practitioner |
| H-0119 | Idiosyncratic 5-minute drop, bought | Nagel (2012) |
| H-0120 | Previous-day high/low break | practitioner |

The papers are cited from memory and earlier notes (research 019, 071, 153,
161); none was re-fetched for this note. Five of the ten are near relatives
of rules that already failed at 12.24 bps (named in each card's red flags);
they are re-tested because the cost is now 8.46 bps.

## Earlier stock rules against the new cost

From their recorded gross edge, without re-running. Rules whose gross edge a
trade was above 8.46 bps: H-0065 overnight-winner reversal (13.86, already
PAPER), H-0078 market-move laggards (16.68, all of it in 2022), H-0096 ban
short (45.46, PROMOTE). Just below: H-0084 MAX 7.70, H-0042 shock fade 7.69,
attention at +5% 7.83, H-0045 in-play ORB 6.32. None of those is re-gated
here: changing the size after seeing the results would be choosing on them.

## Results

Screen 2026-11-07 (`make mft-screen`), then the gate for the three whose
halves were both net positive. Bps a trade at ₹5 lakh; cost 8.46-8.47 bps a
trade; Sharpe and drawdown on the ₹10 lakh of margin.

| Card | Trades a day | Gross | Net | Net Sharpe | Halves | Drawdown | Verdict |
|---|---|---|---|---|---|---|---|
| H-0111 | 3.01 | -1.26 | -9.73 | -2.25 | -3.744 / -0.74 | -71% | screen fail |
| H-0112 | 5.7 | -0.37 | -8.84 | -2.421 | -2.617 / -2.21 | -87% | screen fail |
| H-0113 | 4.47 | 7.5 | -0.96 | -0.202 | -1.798 / 0.316 | -48% | screen fail |
| H-0114 | 3.12 | 7.24 | -1.23 | -0.249 | 0.016 / -0.538 | -26% | screen fail |
| H-0115 | 6.02 | 13.3 | 4.84 | 0.84 | 0.343 / 1.326 | -32% | **PAPER** |
| H-0116 | 3.06 | -3.24 | -11.7 | -1.303 | -1.319 / -1.306 | -79% | screen fail |
| H-0117 | 11.6 | 10.01 | 1.54 | 0.433 | 0.686 / 0.18 | -63% | KILL |
| H-0118 | 3.26 | 17.23 | 8.77 | 0.842 | 0.833 / 0.85 | -29% | **PAPER** |
| H-0119 | 1.93 | 5.79 | -2.68 | -0.275 | 0.591 / -0.846 | -35% | screen fail |
| H-0120 | 12.16 | 4.66 | -3.81 | -0.866 | -0.496 / -1.221 | -95% | screen fail |

1. **Two PAPER, no PROMOTE.** H-0118 (noon pullback on a trend day) and
   H-0115 (gap fade after the first 15 minutes turn) are the first stock price
   rules here to clear costs. Both missed promotion on probabilistic Sharpe
   (0.921 and 0.928 against 0.95) over 2.9 years; H-0115 also turns negative at
   2x costs. Under ADR-141 they may be paper-traded, not traded live.
2. **The size did it.** At ₹1 lakh (12.24 bps) both would be near zero net, from gross less cost
   (H-0118 +5.0, H-0115 +1.1 bps). At 2x costs H-0118 keeps a Sharpe of 0.03.
   So the result rests on the 2 bps slippage assumption; H-0118 survives only
   if real slippage is not much worse.
3. **Both are against the morning move or with the trend after a pause, and
   both cut their losses**: H-0115 targets the previous close with a 1% stop;
   H-0118 enters after a 0.5% pullback.
4. **The lead-lag and reversal ideas from the MFT literature have no gross edge
   on NSE 5-minute closes** (H-0111 -1.26, H-0112 -0.37 bps). Industry and
   late-day momentum make 7-7.5 bps gross, under cost.
5. H-0117 (midday range break) KILL: negative at 2x costs, below the paper
   bar's probabilistic Sharpe. Dead.
6. With ten rules tried and no search correction in simple mode, two
   survivors at Sharpe 0.84 are consistent with luck. Paper trading is the
   test that can tell.
