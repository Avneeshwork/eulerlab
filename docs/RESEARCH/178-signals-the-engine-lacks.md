# 178 — Ten rules on signals the autopilot's engine lacks

**Question.** Operator, 2026-11-08: "keep building strategies and process to
deploy paallely". The nightly autopilot (ADR-150) now writes ten rules a night
in research 173's frame from a fixed signal list. These ten use signals that
list does not have, in the same frame (the 500 most traded NSE stocks each
day, daily bars, 1x, BE/BZ skipped).

**Status.** H-0184 to H-0193 pre-registered and committed before any run.
Results follow under "Results".

| Card | Kind | New signal |
|---|---|---|
| H-0184 | intraday | close at the high on a 10%/20% rise (price-limit close): short next day |
| H-0185 | intraday | close at the low on a 10%/20% fall: buy next day |
| H-0186 | intraday | India VIX +15% yesterday: buy yesterday's ten biggest losers |
| H-0187 | intraday | the day after a 5% results reaction: follow it |
| H-0188 | intraday | institutional bulk buy (fund, insurer, pension): buy next day |
| H-0189 | swing, 20 | institutional bulk buy |
| H-0190 | swing, 20 | 5% up results reaction |
| H-0191 | swing, 10 | price-limit close at the high |
| H-0192 | swing, 20 | five sessions of 1.5x delivery with a flat price |
| H-0193 | swing, 10 | India VIX +15%: buy the ten biggest losers |

Institutional clients are named by a fixed list of words in the bulk-deal
client name (MUTUAL FUND, INSURANCE, LIFE, PENSION, SICAV, ASSET MANAGEMENT,
TRUSTEE, " FUND"), set before any run. Papers are cited from memory. A pass
is checked against H-0161, H-0168 and H-0162 for being the same bet.

## Results

Screen 2026-11-08 (`make new-signals`), then the gate for the four passes
that were not the same bet as an earlier survivor (ledger #132-#139).

| Card | Count | Gross | Net | Net Sharpe | Halves | At 2x costs | Verdict |
|---|---|---|---|---|---|---|---|
| H-0184 | 1562 | 22.55 | 10.3 | 0.198 | -0.248 / 0.626 | -0.036 | screen fail |
| H-0185 | 568 | 100.94 | 88.64 | 0.731 | 0.888 / 0.532 | 0.633 | **PROMOTE** |
| H-0186 | 300 | 61.95 | 49.66 | 0.248 | 0.243 / 0.318 | 0.188 | PAPER |
| H-0187 | 935 | 78.91 | 66.63 | 2.578 | 2.318 / 2.813 | 2.135 | **PROMOTE** |
| H-0188 | 252 | -20.77 | -33.03 | -0.892 | -0.387 / -1.298 | -1.205 | screen fail |
| H-0189 | 189 |  | 195.57 | 0.889 | 0.33 / 1.277 | 0.768 | screen pass; same bet as H-0162 |
| H-0190 | 150 |  | 199.86 | 0.666 | -0.543 / 1.772 | 0.578 | screen fail |
| H-0191 | 973 |  | 73.94 | 0.379 | 0.574 / 0.181 | 0.244 | PAPER |
| H-0192 | 863 |  | 120.77 | 0.656 | 0.383 / 0.965 | 0.513 | screen pass; same bet as H-0162 |
| H-0193 | 229 |  | -188.71 | -0.341 | -0.501 / -0.135 | -0.389 | screen fail |

1. **H-0187 PROMOTE**: on the session after a results reaction of 5% or more,
   trading with it from open to close earns +67 bps net a trade on 935 trades
   (2021-07 to 2024-11), every year positive, 2.14 Sharpe at 2x costs; deflated
   Sharpe 0.965, so under the strict bar it fails only Romano-Wolf. It is not
   the same bet as H-0168, which fades the reaction morning (correlation 0.01):
   results moves overshoot at the open and then drift in their direction (Chan
   2003's drift, at one day).
2. **H-0185 PROMOTE, but weak**: buying a stock the day after it closed at its
   lower price limit earns +89 bps net a trade but only Sharpe 0.73 over nine
   years, with three losing years; deflated Sharpe 0.001.
3. H-0186 (VIX-jump losers) and H-0191 (limit-up, 10 days) PAPER.
4. H-0189 and H-0192 passed the screen but move with H-0162 (0.51, 0.55):
   long-only swings in a rising market are mostly one bet. Not gated.
5. Institutional bulk buys have no next-day edge (-33 bps net), and limit-up
   closes do not reverse the next day after costs (+10 net, first half
   negative).
