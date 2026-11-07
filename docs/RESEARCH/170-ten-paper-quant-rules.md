# 170 — Ten paper-backed, market-neutral stock day trades

**Question.** Operator, 2026-11-07, after research 169: "first research on 10
more better quality quant strategy". NSE cash stocks, intraday at Zerodha 5x
MIS (ADR-146).

**Status.** H-0131 to H-0140 pre-registered and committed before any run.
Results follow under "Results".

## What "better quality" means here

Research 168-169's scalps were mostly practitioner rules on one side of the
market. These ten differ in four ways, all fixed before any run:

1. **Each comes from a published cross-sectional anomaly** with a named paper
   (cited from memory and earlier notes; none re-fetched for this note).
2. **Market-neutral**: five long and five short each day among the 100 most
   traded F&O stocks, so the Nifty's day cancels out.
3. **One decision a day at 09:20** from information known by then; ten
   trades a day; no stops or targets to tune.
4. **A stricter screen**: gated only if net positive in both halves *and* at
   twice the costs. The gate's own simple mode would pass a rule negative at
   2x costs only if PSR and halves passed; this screen does not.

| Card | Anomaly | Paper |
|---|---|---|
| H-0131 | Overnight gap reversal (residual to Nifty) | Berkman, Koch, Tuttle and Zhang (2012) |
| H-0132 | Tug of war: 20-session overnight return reverses in the day | Lou, Polk and Skouras (2019); parent H-0065 |
| H-0133 | One-day residual reversal | Lehmann (1990); Da, Liu and Schaumburg (2014) |
| H-0134 | High-volume return premium | Gervais, Kaniel and Mingelgrin (2001) |
| H-0135 | Industry momentum, one day | Moskowitz and Grinblatt (1999) |
| H-0136 | Same-hour seasonality at the open | Heston, Korajczyk and Sadka (2010) |
| H-0137 | Weekly residual reversal | Lehmann (1990) |
| H-0138 | Nearness to the 52-week high | George and Hwang (2004) |
| H-0139 | Short-term momentum in high-turnover stocks | Medhat and Schmeling (2022) |
| H-0140 | Industry-relative gap reversal | Berkman et al. (2012); Hou (2007) |

Costs as research 168: ₹5 lakh a position, 8.46 bps a round trip, ten open
on ₹10 lakh of margin. A market-neutral book pays the cost on both legs, so
the spread between the legs must clear about 8.5 bps a position.

## Results

Screen 2026-11-07 (`make quant-screen`), no trial spent; then the gate for
the one rule that passed the stricter screen. Bps a position at ₹5 lakh;
legs are the gross bps of the long and the short side.

| Card | Gross | Long / short legs | Net | Net Sharpe | Halves | At 2x costs | Verdict |
|---|---|---|---|---|---|---|---|
| H-0131 | 9.22 | -0.98 / 19.41 | 0.75 | 0.126 | -0.015 / 0.266 | -1.293 | screen fail |
| H-0132 | 17.35 | 3.68 / 31.02 | 8.89 | 1.439 | 2.357 / 0.442 | 0.069 | **PROMOTE** |
| H-0133 | 4.23 | -14.14 / 22.59 | -4.23 | -0.705 | -1.68 / 0.204 | -2.117 | screen fail |
| H-0134 | -7.75 | -18.23 / 2.73 | -16.21 | -3.042 | -1.986 / -4.047 | -4.63 | screen fail |
| H-0135 | 1.2 | -4.79 / 7.18 | -7.27 | -1.462 | -0.954 / -1.907 | -3.164 | screen fail |
| H-0136 | 0.14 | -7.29 / 7.58 | -8.32 | -2.532 | -3.366 / -1.726 | -5.107 | screen fail |
| H-0137 | 11.88 | -3.31 / 27.07 | 3.42 | 0.548 | 0.395 / 0.695 | -0.803 | screen fail |
| H-0138 | 3.0 | -4.1 / 10.1 | -5.46 | -1.004 | -1.338 / -0.649 | -2.559 | screen fail |
| H-0139 | -5.58 | -14.78 / 3.61 | -14.04 | -2.703 | -2.944 / -2.444 | -4.333 | screen fail |
| H-0140 | 5.37 | -7.48 / 18.22 | -3.09 | -0.659 | -1.525 / -0.017 | -2.46 | screen fail |

1. **H-0132 PROMOTE (ledger #110, #111)**, the tug of war at MIS size: 9 of 9
   simple rules. But it is H-0065 re-sized, chosen knowing H-0065 was PAPER;
   its second half is weak (Sharpe 0.44 against 2.36) and 2024 to October lost
   37% on margin (+602% in 2022, +184% in 2023, compounded at 5x); at 2x costs
   its Sharpe is 0.07; drawdown -47% of margin. It fails the strict bar
   (deflated Sharpe 0.704, Romano-Wolf). Treat it as a decaying effect that
   paper trading must confirm, not as a found edge.
2. **In all ten, the short leg carried the gross and the long leg lost.** NSE
   F&O stocks drift down from 09:20 to 15:10 on average (the daytime half of
   the overnight-daytime split, research 159), so a five-and-five book is
   short that drift as well as long its anomaly. These books are not beta
   neutral; a beta-weighted version would be a new hypothesis.
3. The US anomalies at daily horizons do not appear in one NSE session:
   high-volume premium -7.75 bps gross, industry momentum +1.20, open-hour
   seasonality +0.14, 52-week high +3.00, turnover momentum -5.58.
4. Gap reversal (H-0131) and weekly reversal (H-0137) make 9-12 bps gross,
   above cost but not at 2x costs; one-day reversal makes 4.2.
