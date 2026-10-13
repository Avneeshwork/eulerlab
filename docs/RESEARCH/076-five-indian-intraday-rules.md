# 076 — Five intraday rules from Indian sources, on NIFTYBEES and the 100 largest stocks

**Question.** Operator, 2026-10-12: "work on 5 intraday strategy from recent
paper/article which have possibility to outperform in indian market ... on
indian market purely". Which intraday rules published on NSE data can be coded
from what is readable, and does any survive Indian costs?

**This note was written on 2026-10-13, a day after the code.** The sources
were read on 2026-10-12 by the session that coded them; what each said is
taken from that session's records in `intraday/india_papers.py` and
`strategies/studies.py`. They were not fetched again. The numbers are from a
fresh run on 2026-10-13, which matched the stored run of 2026-10-12 exactly.

## Sources, read 2026-10-12

| Source | URL | Read |
|---|---|---|
| Rao, "All About Opening Range Breakout (ORB), Part 1", Zerodha *In The Money*, 2 March 2026 | https://inthemoneybyzerodha.substack.com/p/all-about-opening-range-breakout | Article. Nifty index, 3-minute candles, January 2019 to February 2026, no costs. Charts only, no table |
| Doraigari, "Best Intraday Breakout Strategy for Nifty 50", IntradayLab, 30 March 2026 | https://intradaylab.com/blog/nifty-orb-breakout-strategy-backtest | Article. Nifty 50 spot, 15-minute candles, July 2017 to March 2026, no costs. Its win count (887 of 2,122) does not match its win rate (48.7%) |
| Wang & Gangwar (2025), "Optimizing Intraday Breakout Strategies on the NSE: A Block-Based Performance Evaluation", SSRN 5198458 | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5198458 | **Abstract only** (SSRN returns 403). Tata Motors, about one year. Bootstrap p-values 0.45 to 0.50 |
| "Hedging Demand and Intraday Momentum within the Indian Stock Market" (2024) | https://www.researchgate.net/publication/383567351 | **Not readable** (403); authors not confirmed. The listing says it applies Baltussen, Da, Lammers & Martens (JFE 2021) to Nifty futures |
| Tripathi & Aggarwal (2015), "Prior Return Effect in Indian Stock Market: An Intra-day Analysis", *International Journal of Financial Management* 5(1) | https://www.publishingindia.com/storage/PDFBrochures/2481.pdf | **In full.** CNX 500 stocks, 2010, 30-minute returns, no costs |
| Memon, Anklesaria-Dalal, Vidhani & Borkar (2026), "Price Discovery or Price Pressure? High-Frequency Evidence from India's New Closing Auction Session", IJLRP 7(10) | PDF in `docs/RESEARCH/papers/` | Read. Not coded: its effect runs from the auction to the next open, which is overnight, not intraday |

Not found: the full text of Wang & Gangwar; the Indian momentum paper's own
rule and numbers; any reviewed Indian intraday paper from the last two years
that is both readable and a rule. Two of the five sources are articles, not
papers, and one paper is from 2015.

## Rules as run

`make india-intraday`. One-minute bars from Kite, 2021-08-20 to 2026-10-12.
The three index rules run on NIFTYBEES (1,266 sessions). The two stock rules
run on the 100 largest companies with minute history, **chosen by today's
market value**, which is survivorship bias.

- **The 09:15 print is never used.** Ranges, signals and fills start at 09:16
  (research 075). Neither article says how it treats the first bar.
- **Late opening range (Rao).** Range 09:16 to 10:15 or to 11:15. The first
  3-minute close outside it is followed at the next minute's open. Stop at the
  other side. No target or exit is published, so out at 15:24.
- **30-minute range, 2R (Doraigari).** Range 09:16 to 09:44. A stop order at
  each edge. Stop at the other edge, target at twice the range, out at 14:30.
  A minute that spans stop and target counts as the stop.
- **Opening range with a volume surge (Wang & Gangwar).** All 18 published
  settings: 5, 15 or 30-minute bars; breakout bar's volume at least 1.2 or 1.5
  times that bar's 20-session average (A-058); hold 2, 3 or 5 bars, or to
  15:10 (A-057). One trade a stock a day, equal slots.
- **Rest-of-day momentum (Baltussen design).** At 15:00, follow the sign of
  the return from the previous official close to 14:59. Out at 15:24. The
  gamma variant is not coded.
- **Fade the extremes (Tripathi & Aggarwal).** At the open and at 12:15, buy
  the three stocks with the lowest half-hour move and short the three with the
  highest. Hold 30 or 150 minutes. Six equal slots.

Costs: `costs.router` at NSE intraday rates, plus slippage a side of 1 bp on
the ETF (A-052) and 2 bps on stocks (A-056). 1x, ₹10 lakh.

## Results, after costs

| Rule | Trades | Gross Sharpe | Gross bps a trade | Net Sharpe | Net return | Net Sharpe before 2024 | From 2024 |
|---|---|---|---|---|---|---|---|
| Late range, to 10:15 | 1,180 | 1.20 | 3.2 | -0.94 | -27.8% | -0.41 | -1.44 |
| Late range, to 11:15 | 1,076 | 1.44 | 3.6 | -0.81 | -21.6% | -0.03 | -1.59 |
| 30-minute range, 2R | 1,248 | 0.85 | 2.0 | -1.67 | -40.3% | -1.73 | -1.61 |
| Rest-of-day momentum | 1,263 | 0.67 | 0.7 | -4.82 | -49.7% | -3.33 | -6.59 |
| Volume surge, 5-minute (6 settings) | 92,000-96,000 | -1.17 to -0.58 | -0.7 to -0.3 | below -22 | -72% to -73% | | |
| Volume surge, 15-minute (6 settings) | 68,000-78,000 | 0.34 to 0.73 | 0.3 to 1.0 | below -9 | -57% to -64% | | |
| Volume surge, 30-minute (6 settings) | 46,000-58,000 | 0.97 to 1.32 | 1.6 to 2.0 | below -7 | -41% to -50% | | |
| Fade at the open, 30 minutes | 7,589 | 2.50 | 8.0 | -0.32 | -15.3% | 0.35 | -0.94 |
| Fade at the open, 150 minutes | 7,590 | 2.10 | 9.0 | 0.12 | +4.0% | 0.96 | -0.59 |
| Fade at midday, 30 minutes | 7,596 | 1.30 | 1.8 | -7.78 | -74.6% | -7.11 | -8.36 |
| Fade at midday, 150 minutes | 7,596 | -0.27 | -1.0 | -4.72 | -83.1% | -4.30 | -5.20 |

Every setting is in `data/derived/india_intraday_papers.json`.

## Findings

1. **Nothing survives costs.** 25 of 26 settings lose money after costs. The
   one that does not, the open fade held 150 minutes, made 4% in five years
   and has lost since 2024.
2. **The opening-range rules have a real but small gross edge**, 2 to 4 bps a
   trade on the ETF, the same size research 071 found for the noise area. A
   round trip in NIFTYBEES costs about 6 bps.
3. **The open fade has the largest gross edge found so far**, 8 to 9 bps a
   trade, as the 2015 paper says. A round trip in a stock costs about 9 bps
   here with slippage. The slippage is assumed, not measured, and these fills
   are in the first minutes of the session.
4. **The volume-surge breakout is not an edge at any setting.** The longest
   range is the least bad. The paper's own tests could not reject luck.
5. **Rest-of-day momentum is absent** on the ETF: 0.7 bps a trade gross.

## Decision

None is a gate candidate. All five are in the strategy library as studies
(`strategies/studies.py`) and in the research library, with every published
setting stored. No trial was recorded: these are screening runs of published
settings, with nothing searched.

**Confidence:** high that none works on the cash ETF or cash stocks at these
costs. Low on what the two unread papers actually claim.

## Open

- The open fade and the late range on a cheaper instrument (futures) are new
  hypotheses, like T-4039. Each needs its own data and its own trial.
- Memon et al. (2026), the closing auction to the next open, is the strongest
  lead found and is overnight, not intraday. Not coded.
