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

(Added after the runs.)
