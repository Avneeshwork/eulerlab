# 198 — The robustness battery on four passed cards, and the DP charge on swing screens

**Question.** (1) Do H-0161, H-0168, H-0175 and H-0187 survive the coded robustness battery (#158, ADR-211)? (2) How much does the DP charge take from a swing card's net figure (#153)?

**Sources.** No web source. Data: the research panel on the Mac, cut at the discovery end (2023-12-31, ADR-210), run 2026-11-16 with `validation/robust_battery.py`. Each run is a `robust` row in the experiment store. DP charge: A-156 (Angel One, ₹23.60 a delivery sell, not fetched this session); the issue's Zerodha figure (₹15.34, https://zerodha.com/charges, fetched 2026-11-13 by the audit) is not used.

**How each card was run.** H-0175 from its `engine:` block; H-0168 from research 176's reference rule. H-0161 and H-0187 are research code, not engine rules, so they were written in the engine's language for this run: H-0161 as `short when delay(ret(1),1) >= 0.03 and delay(delivery_ratio,1) <= 0.5, lowest delivery first`; H-0187 as `trade with delay(ret(1),1) when delay(results_morning,1) and |delay(ret(1),1)| >= 0.05, largest move first`. The translations are close, not identical (the research code's universe and split filters differ in detail), so their figures are the translation's.

**Findings (discovery period; window starts 2005 for price rules, 2021-07 for results rules).**

| Card | Trades | Net bps each | Net Sharpe | Neighbours | Halves (median) | Placebos (mean) | Regimes (largest share a session) | Battery |
|---|---|---|---|---|---|---|---|---|
| H-0161 | 21,626 | 64.07 | 3.68 | 6 of 7 keep half | 2.90 | 0.67 | 71% before peak margin | pass |
| H-0168 | 669 | 26.67 | 1.12 | 2 of 2 keep half | 0.73 | -0.73 | 100% Nifty above its 200-day mean (loses below) | FAIL |
| H-0175 | 24,957 | 204.91 | 9.74 | 5 of 5 keep half | 7.68 | 1.41 | 84% before peak margin | FAIL |
| H-0187 | 575 | 77.43 | 2.83 | 6 of 8 keep half | 2.19 | -0.51 | 58% India VIX low tercile | pass |

1. No card is a lucky point, a lucky set of stocks or a leak: every one keeps half its Sharpe in most neighbours, has a positive median on random half universes, and its placebos make far less than it does.
2. H-0168 earns only when the Nifty is above its 200-session mean (0.036% of capital a session) and loses slightly below it (-0.003%). One state holds all its profit.
3. H-0175's daily profit before September 2021 is 5.2 times its profit after (1.21% against 0.23% of capital a session). Most of its edge is in the years before SEBI's peak-margin rules, and research 180 already found it overstated by the opening print. H-0161 shows the same decline (0.32% to 0.13%), inside the 80% line.
4. H-0175's net 204.91 bps a trade and Sharpe 9.74 are not credible as fills (research 180); the battery tests whether the backtest is fragile, not whether its prices are tradable.

**DP charge (#153).** Screens now charge ₹23.60 on every delivery sell (ADR-203's switch, applied in `Engine.screen`, the engine's gate run and the selection check). Intraday rules pay nothing extra. A swing position pays it once:

| Position size | DP a round trip |
|---|---|
| ₹1,00,000 (the screens' size: ten positions on ₹10 lakh) | 2.36 bps |
| ₹10,000 (ten positions on the constitution's ₹1 lakh) | 23.6 bps |

At the screens' size every swing card's net figure falls by 2.36 bps a position; none of the swing cards with a positive net figure in their result line is within 2.36 bps of zero (smallest: H-0151 at 20.12 bps, H-0154 at 24.99). At ₹10,000 positions, H-0151 (20.12) would turn negative, H-0154 (24.99) and H-0170 (25.4) would be near zero, and the rest (H-0153 331, H-0155 38, H-0162 395, H-0182 59, H-0189 196, H-0190 200) would stay positive. The screens still size at ₹1 lakh a position; screening at the constitution's size is a separate change.

**Decision.** H-0168 and H-0175 would not have reached the gate under the battery. Nothing is re-gated here: their verdicts stand until the operator decides (T-4656). DP is charged in every screen from today.

**Confidence.** High for the battery's arithmetic (unit-tested, deterministic). Medium for H-0161 and H-0187 (translations). Medium for the DP figure (A-156 unfetched).

**Open.** The peak-margin date (A-160) is from memory. Screen at the constitution's position size. The paper books do not yet pay DP (T-4633).
