# 179 — Four more signals on every liquid NSE stock

**Question.** Operator, 2026-11-08: "continue". More strategies in research
173's frame, on signals neither the engine nor earlier batches used.

**Status.** H-0194 to H-0197 pre-registered and committed before any run.
Results follow under "Results".

| Card | Kind | Signal | Paper |
|---|---|---|---|
| H-0194 | intraday | 3% gap with no NSE filing: fade | Chan (2003) |
| H-0195 | intraday | promoter sale (SAST): short next session | Lakonishok and Lee (2001) |
| H-0196 | swing | dividend ex-date in ten sessions: buy, sell the day before | Hartzmark and Solomon (2013) |
| H-0197 | intraday | new 250-session low on half the usual delivery: buy | thin-move overshoot, as H-0161 |

Papers cited from memory. Same frame, costs and screen as research 178.

## Results

Screen 2026-11-08 (`make more-signals`).

| Card | Count | Net | Net Sharpe | Halves | At 2x costs | Verdict |
|---|---|---|---|---|---|---|
| H-0194 | 4,828 trades | +121.56 bps | 7.81 | 9.17 / 6.50 | 7.08 | PROMOTE (ledger #140, #141), but see research 180 |
| H-0195 | 527 trades | -11.86 bps | -0.52 | -0.64 / -0.42 | -1.03 | screen fail |
| H-0196 | 1,567 positions | +98.07 bps | 1.05 | 0.62 / 1.45 | 0.77 | screen pass; same bet as H-0162 (0.58), not gated |
| H-0197 | 331 trades | -88.80 bps | -0.73 | -1.01 / -0.21 | -0.82 | screen fail |

H-0194's Sharpe of 7.8 led to research 180: ETFs' stale opening prints and the
auction fill inflate it about twofold. Promoter sales carry no next-day edge,
and buying thin new lows loses.
