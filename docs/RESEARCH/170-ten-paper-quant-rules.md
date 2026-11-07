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

(Added after the runs.)
