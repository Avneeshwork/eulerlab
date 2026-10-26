# 113 — Daily strategies from GitHub and published evidence, on NSE

**Question (operator, 2026-10-18).** Find simple strategies with possible alpha
— first on GitHub, then with published evidence — code them as written, and
backtest them on Indian stocks. Later: is any of them a 40%-a-year strategy?

## Why daily

Research 088-111 ported about a dozen GitHub *intraday* rules to five NSE
stocks; every one lost after costs (2-8 bp a trade against NSE intraday
charges). Research 112 found the same for five intraday rules on 416 F&O
stocks. This round trades daily bars, on the point-in-time 250 most-traded
stocks (`india_papers.liquid_universe`), long only, through the Tier B engine,
2016-01 to 2026-10, delivery costs (STT 0.1% each side, stamp, exchange, SEBI,
GST: about 0.22% a round trip), **no slippage and no DP charge** (both missing
from every figure below; the paper deployments assume 5 bp a fill, A-048).

## Sources (all fetched 2026-10-18)

GitHub (rules read from the code with `gh api`): leo-aa88/larry_connors_rsi2_bot
(RSI(2)); toniker10/SPY-IBS-Mean-Reversion-Strategy (IBS); Harvey-Sun/TurtleTrading
(Turtle 20/10); abeer555/Trend-Radar (trend template, RS weights, frog-in-the-pan
ID, Mansfield RS); AleksLi1/Accelerating_Dual_Momentum; lukelebaudy/Golden-Cross-Backtester;
darshandeshmukh11/supertrend-backtester; Sunkeerth/macd-crossover-backtest-three-frameworks;
mmoraschini/faber-taa; skyte/momentum (Clenow).

Papers and evidence (abstracts and secondary summaries; PDFs could not be
extracted on this machine): Da, Gurun & Warachka (2014) and Goyal, Jegadeesh &
Subrahmanyam (Review of Finance, international); Blitz, Huij & Martens (2011),
Blitz, Hanauer & Vidojevic (2020); Barroso & Santa-Clara (2015); Blitz, Huij,
Lansdorp & Verbeek (2013); Avramov, Kaplanski & Subrahmanyam (2021); Kaniel,
Ozoguz & Starks (2012); Moskowitz & Grinblatt (1999); Van Vliet & Blitz (2018)
and *The Conservative Formula: Evidence from India* (SSRN 4163613); NSE Nifty
Alpha Low-Volatility 30 whitepaper (2020); Barber, De George, Lehavy & Trueman
(2013); Chan, Jegadeesh & Lakonishok (1996); Sharma, Subramaniam & Sehgal
(2021) for which anomalies persist in India. URLs are on each library entry
(`research/papers/`).

**Rejected on the evidence, not coded:** post-earnings drift by EPS surprise
(no EPS surprises held; the announcement-return version was coded instead);
return seasonality (not significant in emerging markets, Li, Zhang & Zheng
2018); the dividend-month premium (mixed abroad, absent in Japan);
volume-conditioned momentum (reverses in emerging markets); the April
tax-loss effect (mixed in India); NSE's Momentum 30 (already in the library as
volatility-adjusted momentum); VCP (fragile swing rule, no evidence); value
and quality (fundamentals have no publication dates).

## Results, 2016-01 to 2026-10 (Nifty buy-and-hold about 11.5% a year)

| Strategy | Per year | Sharpe | Worst drawdown | Fills | First trade | Top-5 share of profit | Per year without top 5 | Alpha a year |
|---|---|---|---|---|---|---|---|---|
| `nse_github_weinstein_stage2` | 29.8% | 1.02 | -54% | 3,562 | 2016-01-13 | 52.0% | 21.3% | 17.0% |
| `nse_github_stocks_on_the_move` | 21.6% | 1.06 | -29% | 14,382 | 2016-01-13 | 16.8% | 19.3% | 12.0% |
| `nse_github_minervini_template` | 20.6% | 0.88 | -41% | 3,603 | 2016-01-13 | 36.5% | 16.0% | 11.2% |
| `india_ma_distance` | 20.1% | 0.86 | -45% | 4,994 | 2016-01-13 | 28.0% | 16.6% | 8.7% |
| `india_scaled_momentum` | 19.2% | 0.89 | -46% | 4,785 | 2016-01-13 | 28.0% | 15.8% | 8.9% |
| `india_frog_in_the_pan` | 19.2% | 0.93 | -40% | 4,697 | 2016-01-13 | 28.8% | 15.7% | 7.7% |
| `nse_github_golden_cross` | 18.3% | 0.90 | -40% | 2,559 | 2016-01-13 | 23.3% | 15.6% | 7.4% |
| `nse_github_supertrend_10_22` | 17.5% | 0.93 | -44% | 6,076 | 2016-01-13 | 28.0% | 14.3% | 8.7% |
| `india_industry_momentum` | 16.9% | 0.79 | -57% | 4,284 | 2016-01-13 | 25.6% | 14.0% | 6.5% |
| `india_residual_momentum` | 14.3% | 0.80 | -46% | 4,027 | 2018-01-24 | 30.6% | 11.3% | 4.9% |
| `india_alpha_low_volatility_30` | 14.0% | 0.91 | -32% | 931 | 2016-01-13 | 24.8% | 11.5% | 4.2% |
| `nse_github_turtle_20_10` | 13.5% | 0.74 | -39% | 5,743 | 2016-01-13 | 43.0% | 9.2% | 5.6% |
| `nse_github_dual_momentum_etf` | 9.8% | 0.68 | -42% | 179 | 2016-01-13 | 100.0% | 0.0% | 4.0% |
| `india_conservative_formula` | 8.2% | 0.59 | -41% | 1,364 | 2018-01-24 | 29.9% | 6.2% | 0.0% |
| `india_residual_reversal` | 7.9% | 0.49 | -51% | 5,650 | 2018-02-26 | 22.3% | 6.4% | -1.2% |
| `india_high_volume_premium` | 5.5% | 0.36 | -60% | 19,202 | 2016-01-13 | 33.7% | 3.8% | -4.5% |
| `nse_github_faber_taa_etf` | 5.3% | 0.54 | -35% | 438 | 2016-01-13 | 100.0% | 0.0% | 2.5% |
| `nse_github_ibs_niftybees` | 4.9% | 0.47 | -34% | 576 | 2016-01-13 | 100.0% | 0.0% | -1.5% |
| `nse_github_rsi2_daily` | -3.5% | -0.08 | -58% | 10,698 | 2016-01-13 | — | -6.5% | -11.1% |
| `nse_github_macd_crossover` | -4.7% | -0.13 | -74% | 13,202 | 2016-01-13 | — | -7.0% | -13.2% |

Attribution columns from `attribution.py` (research 114): the share of profit
from the five best holdings, the return a year with those five removed, and
annual alpha against the Nifty 50. ETF rules hold one instrument at a time,
so their top-5 share is 100% by construction.

Three strategies need 36 months of history and first traded in 2018: their
figures above run from 2018 (Nifty about 9.9% a year since then).

## Event strategies (announcement data 2021-07 to 2024 only)

| Strategy | Window | Per year | Sharpe | Worst drawdown | Fills | Top-5 share | Without top 5 | Beta | NIFTYBEES per year |
|---|---|---|---|---|---|---|---|---|---|
| `india_drift_momentum_combo` | 2021-08-03 to 2024-11-29 | 39.7% | 1.55 | -26% | 973 | 42.5% | 25.6% | 1.08 | 14.3% |
| `india_announcement_drift` | 2021-08-03 to 2024-11-29 | 31.8% | 1.50 | -18% | 1,218 | 22.8% | 25.4% | 1.01 | 14.3% |
| `india_earnings_announcement_premium` | 2021-08-03 to 2024-11-29 | 0.2% | 0.06 | -15% | 2,213 | — | -1.3% | 0.24 | 14.3% |

The two drift strategies have the highest Sharpe ratios of the round, and the
edge is broad (about 25% a year without the five best). **The window decides
too much.** Run to 2025-02 (the unwindowed run, which held positions into the
Dec 2024-Feb 2025 sell-off), the combo earns 30.6% and drift 22.1% a year
against the Nifty's 12.1%. Three and a third years, a strong small- and
mid-cap market, no slippage, weekly trading: a lead for a longer announcement
history, not an established edge. The combo (drift filtered by Clenow's trend
score) was declared before it was run.

## Corrections made during the round

1. **Equal shares re-sized every position daily.** `PositionRule` and three
   event/volume strategies gave every qualifying stock 1/max(n, slots); as n
   moved, every holding was trimmed or topped up, each paying STT. Fixed to a
   fixed 1/slots, longest-held kept (`tests/test_github_daily.py`). Before and
   after, per year: golden cross 12.9% -> 18.3% (122,004 -> 2,559 fills);
   Supertrend 7.9% -> 17.5%; Turtle 7.1% -> 13.5%; RSI(2) -4.2% -> -3.5%;
   MACD +3.1% -> -4.7% and the high-volume premium 8.4% -> 5.5% (the old
   versions held 100+ names and were costly index funds; the signal alone
   loses). HISTORY #26.
2. **The batch ignored `--from`/`--to`.** The daily path read only `days`;
   the event strategies ran 2016-2026 and held positions into 2025. Fixed in
   `server.windowed` (`tests/test_events_daily.py`); the events were re-run.
   The ten-year sets ran to 2026-10-16 instead of 2026-09-30, immaterial.
   HISTORY #27.

## Trials

Every configuration above is one trial: 20 ten-year strategies and 3 event
strategies, each run twice where a fix applied. One declared variant was run
and then dropped at the operator's request: Clenow top 10 instead of 25
(17.5% a year, Sharpe 0.76, drawdown -47%: worse than the original). These
are screening runs and, as for research 064's India papers, not in the trial
ledger (T-3321); the count is stated here so the noise bar can be charged.

## Findings

- Rules that rebalance monthly and ride established uptrends — momentum in
  any of its forms (Clenow, Minervini, MA distance, frog-in-the-pan, scaled,
  golden cross, Supertrend, Weinstein) — beat the Nifty by 5-18 points a year
  after delivery costs, with drawdowns of 29-57%.
- Their edge is broad: with the five best holdings removed every one still
  beats the Nifty, and alpha against the Nifty is 7-17% a year.
- Anything that trades weekly or faster on a small per-trade edge (RSI(2),
  MACD, high-volume premium, residual reversal, announcement premium) loses to
  STT. ETF timing rules (dual momentum, Faber, IBS) trail buy-and-hold.
- Nothing clears the noise bar (Sharpe 3.0); the best Sharpe is 1.06 (Clenow),
  below the library's best (1.23, volatility-adjusted momentum top 10).
- No strategy earns 40% a year over the decade. Weinstein Stage 2 earns 29.8%
  at a -54% drawdown; concentrating Clenow to 10 names lowered its return. The
  drift + momentum combo shows 39.7% a year, but over 3.3 years that end
  just before a fall; to 2025-02 it is 30.6%.

## Confidence

High in the arithmetic (the attribution reconciles to the paisa) and in the
ranking between momentum-type and fast-trading rules. Medium in the levels:
no slippage or DP charges; equal weights; today's universe of companies in the
company digest; the momentum results overlap one another and the strategies
already in the library, so they are not independent evidence.

## Open questions

Slippage and DP charges per fill (operator to decide); a longer announcement
history for the drift strategies; Brinson attribution once sector weights are
held; whether any of these survives the holdout (not read).
