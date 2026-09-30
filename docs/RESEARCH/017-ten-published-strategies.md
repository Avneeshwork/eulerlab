# 017 — Ten published strategies, and which of our data can test them

**Fetched:** 2026-08-21

The operator asked for ten strategies "from the internet" run against the
landed datasets. `CLAUDE.md` forbids inventing a source, so each one below is a
named, published paper with a URL — not a blog description of one.

**Registering a strategy costs nothing. Evaluating one is search**, and the
workbench performs that search without the ledger recording it (T-3321). Ten
strategies is therefore ten unrecorded searches unless they go through
`make validate`, and that is the honest frame for what follows.

---

## The papers

| # | Strategy | Source | Fetched |
|---|---|---|---|
| 1 | Cross-sectional momentum, 12-1 | Jegadeesh & Titman (1993), *J. Finance* 48(1) — [bauer.uh.edu PDF](https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf) | 2026-08-21 |
| 2 | Short-term reversal, 1 month | Jegadeesh (1990); Lehmann (1990) — cited in [George & Hwang](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf) | 2026-08-21 |
| 3 | Low-volatility anomaly | Baker, Bradley & Wurgler (2011), *FAJ* 67(1) — [NYU Stern PDF](https://pages.stern.nyu.edu/~jwurgler/papers/faj-benchmarks.pdf) | 2026-08-21 |
| 4 | 52-week high | George & Hwang (2004), *J. Finance* 59(5) — [bauer.uh.edu PDF](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf) | 2026-08-21 |
| 5 | Illiquidity premium | Amihud (2002), *J. Financial Markets* 5(1) | 2026-08-21 |
| 6 | Size effect | Banz (1981), *JFE* 9(1) | 2026-08-21 |
| 7 | Multi-factor composite | the standard construction; no single paper | — |
| 8 | Time-series momentum | Moskowitz, Ooi & Pedersen (2012), *JFE* 104(2) — [NYU Stern PDF](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) | 2026-08-21 |
| 9 | Cross-sectional crypto momentum | Liu & Tsyvinski (2021), *RFS* 34(6) — [NBER w24877](https://www.nber.org/papers/w24877) | 2026-08-21 |
| 10 | Fund performance persistence | Carhart (1997), *J. Finance* 52(1) | 2026-08-21 |

### What the sources actually say

**Momentum (1).** Buy the past 3–12 month winners, sell the losers; roughly 1%
a month abnormal return over 3–12 month holding periods. The formation window
runs month −12 to −2, **skipping the most recent month** to avoid the
short-term reversal in (2). That skip is the "12-1" and it is not decoration —
without it the two effects fight.

**Reversal (2).** Over a one-month horizon the sign flips: last month's losers
outperform. This is why (1) skips a month, and the two are separate phenomena
rather than one effect measured badly.

**Low volatility (3).** Over 41 years, high-volatility and high-beta US stocks
*underperformed* low-volatility ones — the opposite of what risk pricing
predicts. The proposed cause is institutional: a mandate to maximise
information ratio against a fixed benchmark without leverage discourages
arbitraging exactly this.

**52-week high (4).** Nearness to the 52-week high forecasts returns and
*dominates* past-return momentum. Notably, these forecasts **do not reverse in
the long run**, which momentum's do.

**Time-series momentum (8).** Different from (1): each asset is judged against
*its own* past, not against a cross-section. Positive past-12-month return →
go long; negative → go short. Profitable in 58 of 58 futures markets tested.

**Crypto momentum (9).** Liu & Tsyvinski find three common factors in
cryptocurrency returns — market, size and momentum — and a strong *time-series*
momentum effect. Crypto is not a separate universe of anomalies; it shows the
same ones.

---

## What our data can actually test

This is the part that matters and the part a list of papers hides.

| Strategy | Needs | Have it? |
|---|---|---|
| 1–7 (equity) | daily cross-section, 2,869 days | **Yes** — the panel, and every feature already exists |
| 8 (time-series momentum) | per-asset own history, any class | **Partly** — the shape does not fit `target_weights`; it is a per-asset signal, not a cross-sectional rank |
| 9 (crypto momentum) | crypto in a `MarketView` | **No** — 52.5M minute candles are landed, but nothing joins them to the engine |
| 10 (fund persistence) | NAV panel | **No** — 21.7M NAV rows are landed, and the panel is equities-only |

So **seven of the ten are runnable today** and three are declarations against
data we hold but have not wired. That is recorded per strategy rather than
smoothed over: a console that lists ten and can run seven should say which
seven.

The blocker for 9 and 10 is the same one ADR-037 names — `MarketView` is keyed
by symbol and carries daily `PanelRow`s, so neither a minute candle nor a NAV
series can be expressed in it. It is one fix, not three.

---

## Confidence and what is not claimed

**These are published findings, not predictions about Indian equities.** Every
paper above is predominantly US evidence over periods ending years ago. Number
(1) is the most replicated result in the literature and *still* had its
premium decay after publication; the 30-years-later reviews found in this
search exist precisely because that is contested.

Nothing here has been backtested by this project yet. When it is, the noise bar
applies: 19 trials are logged and a candidate needs Sharpe 1.88 before beating
it means anything — and that bar itself rests on an unmeasured σ_SR (A-021).

## Open questions

1. Do (1) and (4) survive Indian transaction costs? STT and stamp duty are
   levied per trade and a monthly rebalance pays them twelve times a year.
2. Is (3) confounded here by the fact that low-volatility Indian names are
   disproportionately illiquid, making (3) and (5) the same bet?
3. (9) needs the crypto data joined to the engine before it is more than a
   citation.
