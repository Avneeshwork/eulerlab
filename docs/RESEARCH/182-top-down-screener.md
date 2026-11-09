# 182 — A top-down screener: strong sectors, then strong industries, then good stocks (pre-registered)

**Written 2026-11-08 before any configuration below was backtested.**

## Question

The operator, 2026-11-08: a market brief that suggests daily picks and stocks
likely to make a large move, plus long-term and swing screeners for retail use,
"expected more than 20% a year", with stable selection, good momentum and
fundamentals, and news/earnings timing on when to buy. The screen should go top
down: first the top 5 sectors likely to rise, then the top industries, then
stocks with good momentum that are discounted now.

## Sources

- A. Moskowitz and Grinblatt, "Do Industries Explain Momentum?", JF 54(4) 1999,
  abstract at https://ideas.repec.org/a/bla/jfinan/v54y1999i4p1249-1290.html,
  fetched 2026-11-08. Full text not read.
- B. Sehgal and Jain, "Short-term momentum patterns in stock and sectoral
  returns: evidence from India", J. Advances in Management Research 2011,
  https://www.emerald.com/insight/content/doi/10.1108/09727981111129327/full/html,
  fetched 2026-11-08 (abstract and summary page only; no return figures shown).
- C. Asness, Porter and Stevens, "Predicting Stock Returns Using
  Industry-Relative Firm Characteristics", AQR working paper 2000,
  https://www.aqr.com/Insights/Research/Working-Paper/Predicting-Stock-Returns-Using-IndustryRelative-Firm-Characteristics,
  search summary 2026-11-08; PDF not read.
- D. Agarwal and Sridharan, IIM Bangalore working paper 2013, post-earnings drift
  over 120 days on NSE, https://repository.iimb.ac.in/handle/2074/17935 — search
  summary only; the page failed its TLS check on 2026-11-08 and was not read.
  Gupta and Dhusia 2021 (https://journals.vutbr.cz/index.php/trends/article/view/541,
  search summary) find NSE largely efficient to announcements: the Indian
  evidence on drift is mixed.
- E. Novy-Marx, "Fundamentally, Momentum is Fundamental Momentum", NBER WP 20984
  (paper card in `research/papers/`, abstract only).
- F. This project: research 150-152 (the screener, its blends and consensus);
  research 113 and `data/derived/events_daily.json` (announcement drift
  2021-08 to 2024-11: Sharpe 1.50, +146%; drift with Clenow trend: Sharpe 1.55,
  +197%, drawdown -26%; Nifty ETF +58%); H-0187 (follow a 5% results reaction
  the next day, intraday, PROMOTE).
- G. Measured: screener.in snapshots hold a 3- or 4-level classification for
  2,048 companies (level 1 broad sector, level 2 sector, 40 of them; level 3
  industry; level 4 basic industry). Quarterly results go back only about 12
  quarters (to 2023), so quarterly earnings growth cannot be tested over
  2016-2026; annual statements can.

## Findings

- Industry momentum is strong and explains much of stock momentum in the US (A);
  in India sector momentum exists and absorbs part of stock momentum (B, 6-6
  stronger than 12-12). This supports ranking sectors first, on about 6 months.
- Characteristics measured against the stock's own industry predict better than
  raw ones (C). "Discounted" is therefore defined as cheap against industry
  peers, not cheap against the whole market (research 150's value model, raw
  value, made Sharpe 0.70 against quality momentum's 1.01).
- Earnings news explains price momentum (E) and the drift after results is the
  strongest timing signal this project holds (F), but its data covers only
  2021-08 to 2024-11.
- Nothing found shows a stock rule with "stable" 20%+ a year in India. The best
  stored long-term models made about 20-22% a year 2016-2026 after costs with
  drawdowns of 29-56% (research 152).

## The configurations (fixed; no others will be run)

Common to all: the liquid 250 each date (`liquid_universe`), Tier B engine,
Indian costs, 2016-01-01 to 2026-09-30 unless said. **Sector** = level 2,
**industry** = level 3, today's tag (applied backwards: see red flags). A
sector or industry score is the equal-weighted mean 126-session return of its
members in the liquid 250, counted only with 3 or more members.

| Id | Kind | Rule | Rebalance |
|---|---|---|---|
| `screen_topdown_sectors` | long | Every liquid stock in the top 5 sectors, each sector 1/5, equal inside it. Tests the premise alone. | 21 |
| `screen_topdown_quality_momentum` | long | Top 5 sectors; inside them, industries scoring above the median industry; stocks with quality at or above the median; top 20 by 12-month Sharpe momentum, at most 6 from one sector. | 21 |
| `screen_topdown_discount` | long | Same funnel; earnings yield positive; score = mean of the Sharpe momentum rank and the rank of earnings yield minus its industry's median (cheaper than peers); top 20, at most 6 a sector. | 21 |
| `screen_topdown_pullback` | swing | `screen_trend_pullback` (RSI(2) dip above a rising 200-day) restricted to the top 5 sectors. | 5 |
| `screen_topdown_breakout` | swing | `screen_52w_breakout` (new 52-week high on 2x volume) restricted to the top 5 sectors. | 5 |
| `india_drift_momentum_topdown` | swing | `india_drift_momentum_combo` restricted to the top 5 sectors; 2021-08 to 2024-11 only (the announcement data). | 5 |

Six configurations. Each is run on the full window, on 2016-2020 and
2021-2026, and at twice the costs. Results are appended below without editing
the above.

## The rule for choosing what the brief shows (fixed before running)

- A top-down model replaces the current list of its kind only if its worse
  half's Sharpe beats the current list's worse half (long: the consensus,
  0.48; swing: swing A, 0.73) and it stays positive at 2x costs. Otherwise the
  current list stays and the top-down result is shown beside it.
- The sector ranking is shown in the brief whatever happens, with
  `screen_topdown_sectors`'s result beside it, so the reader sees whether
  "top 5 sectors" has worked here.

## Red flags

- Sector tags are today's: a company that changed business carries its current
  tag back to 2016. Fundamentals exist only for companies alive in 2026
  (survivorship, `fundamentals/annual.py`).
- The swing and long parts were chosen because they had done well (research
  150-152); a sector filter on them inherits that selection.
- Four of the parts are momentum; a sector filter is more momentum. Expect this
  to be close to one bet with the existing lists (HISTORY #44).
- Screening runs only: no trial spent, not judged by the gate.

## Confidence

Not applicable before running.

## Results (appended 2026-11-08 after the runs; nothing above was edited)

`make topdown-screen` (`research.topdown_run`), Tier B, realistic Indian costs,
liquid 250. Full window 2016-01 to 2026-09 (NIFTYBEES +221%, about 11.4% a year,
before costs); the two drift rules 2021-08 to 2024-11 (NIFTYBEES +58%). Halves:
2016-2020 / 2021-2026 (drift: to 2023-03 / from 2023-04). The current lists were
re-run through the same path and match their stored Sharpes to within 0.01.

One decision was taken while writing the code and before any run, and is
recorded here as the pre-registration did not cover it: an industry with fewer
than 3 liquid members inherits its sector's score instead of being dropped.

| Id | A year | Sharpe | Worst fall | Halves | Worse half | 2x costs Sharpe (a year) | Years up |
|---|---|---|---|---|---|---|---|
| `screen_topdown_sectors` | +15.6% | 0.80 | -48% | 0.60 / 1.07 | **0.60** | 0.75 (+14.3%) | 5 of 11 |
| `screen_topdown_quality_momentum` | +14.6% | 0.76 | -47% | 0.60 / 1.19 | **0.60** | 0.70 (+13.2%) | 6 of 11 |
| `screen_topdown_discount` | +16.5% | 0.79 | -59% | 0.48 / 1.29 | **0.48** | 0.74 (+15.1%) | 6 of 11 |
| `screen_consensus_3of5` (current long) | +20.3% | 0.88 | -56% | 0.48 / 1.33 | **0.48** | 0.84 (+18.9%) | 7 of 11 |
| `screen_quality_momentum` | +20.4% | 1.01 | -42% | 0.66 / 1.36 | **0.66** | 0.97 (+19.5%) | 8 of 11 |
| `nse_github_stocks_on_the_move` | +21.5% | 1.08 | -29% | 0.65 / 1.32 | **0.65** | 0.98 (+19.2%) | 9 of 11 |
| `screen_topdown_pullback` | +5.5% | 0.79 | -14% | 0.91 / 0.48 | **0.48** | 0.48 (+3.2%) | 8 of 11 |
| `screen_trend_pullback` | +5.9% | 0.40 | -53% | 0.21 / 0.55 | **0.21** | 0.01 (-1.6%) | 7 of 11 |
| `screen_topdown_breakout` | +9.2% | 0.97 | -14% | 1.05 / 0.75 | **0.75** | 0.83 (+7.8%) | 7 of 11 |
| `screen_52w_breakout` | +15.7% | 0.84 | -39% | 0.49 / 0.90 | **0.49** | 0.71 (+12.8%) | 8 of 11 |
| `screen_swing_mom_weinstein` (current swing) | +22.2% | 1.01 | -41% | 0.73 / 1.18 | **0.73** | 0.93 (+20.1%) | 8 of 11 |
| `india_drift_momentum_topdown` | +24.8% | 1.18 | -20% | 0.14 / 1.66 | **0.14** | 1.07 (+21.9%) | 3 of 4 |
| `india_drift_momentum_combo` | +35.8% | 1.49 | -24% | 0.85 / 1.76 | **0.85** | 1.40 (+33.2%) | 4 of 4 |

What this shows:

- **Picking the top 5 sectors first did not add return here.** Every long model
  with the sector funnel made less a year than the same idea without it
  (quality momentum 20.4% → 14.6%; drift 35.8% → 24.8%). Holding the top 5
  sectors alone made 15.6% a year, consistent with the two earlier sector tests
  (`india_sector_rotation` Sharpe 0.84, `india_industry_momentum` 0.79). A
  stock's own momentum already carries its sector's (Moskowitz and Grinblatt);
  filtering on the sector again throws away strong stocks in average sectors.
- **For swing rules the filter cut the worst fall from about 40-53% to 14%**,
  mostly by holding fewer names and more cash: the return fell with it
  (breakout 15.7% → 9.2% a year).
- **Cheap against industry peers did not help**: the discount model had the
  deepest fall (-59%) and the weakest first half.
- **No rule made 20% in every year.** The best long model, Stocks on the Move,
  rose in 9 of 11 years; its losing years were 2018 (-9%) and 2025 (-1%). The
  results-drift rule made 36% a year with every year up, but over 3.3 years
  only.

**By the rule fixed above** (replace only on a better worse half, positive at 2x
costs): `screen_topdown_sectors` (0.60) would replace the consensus (0.48) as
the long list, and `screen_topdown_breakout` (0.75) would replace swing A (0.73).
Both make less a year than what they replace. The rule compared each top-down
model only with the current list, not with the current list's own parts: two of
those (quality momentum 0.66, Stocks on the Move 0.65) beat both top-down picks
on the same test. `config/screener.yaml` is operator-owned and was not changed;
the choice is put to the operator.

## Confidence (after the runs)

Medium that the sector funnel adds nothing to these momentum models on this
data. Low on any single number: survivorship (fundamentals and tags only for
2026's companies), today's tags applied backwards, and about 30 screener
configurations now tried across research 150-152 and 182.
