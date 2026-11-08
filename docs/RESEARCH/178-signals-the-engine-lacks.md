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

(Added after the run.)
