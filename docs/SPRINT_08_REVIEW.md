# Sprint 08 — feature library and IC harness
**Status:** COMPLETE
**Branch:** sprint-08-features-ic

## What now works (plain English, no jargon)

- **You can now ask "does this idea predict anything?" and get an answer in
  about a minute.** `make ic FEATURE=momentum_12_1` scores a signal against
  what actually happened next, across every stock, on 892 trading days. This
  is the first thing in the project that is about *making money* rather than
  about the data being correct.

- **Ten starting signals**, covering momentum, reversal, volatility,
  liquidity, drawdown and volume. One of them (`small_size`) I expect to be
  poor and said so in its own docstring — a library containing only ideas I
  already believe in would tell me nothing about whether the measuring
  instrument works.

- **The measuring instrument is calibrated at both ends.** A test feeds it a
  signal that secretly *is* the future return, and it must score exactly 1.0.
  Another feeds it pure noise, and it must score ~0. Without those two
  anchors, a number in the middle means nothing. Both hold.

- **Prices are adjusted before any feature sees them.** Sprint 5's work pays
  off here: on raw prices, a 1:1 bonus looks like a 50% crash, so a momentum
  signal would rank that stock the worst in the market on a day its holders
  lost nothing.

- **Every evaluation is counted, permanently.** `CLAUDE.md` requires an
  append-only trial log, and this is the first sprint that evaluates anything,
  so it starts here rather than in Sprint 13 when it is first used. A count
  that starts late looks authoritative while undercounting — and it
  undercounts in the flattering direction.

## The result, and how much to believe it

The full sweep of all ten features produced **zero** results indistinguishable
from noise, and seven with |t| > 3.

**That is a warning, not a success.** Genuine feature research kills most
candidates; a sweep that kills none is measuring something other than ten
separate effects. So I checked, by correlating the features' period-by-period
IC series — and they collapse into **three** groups:

| group | members | internal correlation |
|---|---|---|
| stability | low_volatility, max_drawdown, price_to_52w_high | +0.86 to +0.95 |
| liquidity / size | turnover_liquidity, illiquidity_amihud, small_size | 0.61 to 0.94 |
| momentum | momentum_12_1, momentum_6_1 | +0.79 |

Seven "significant" features are therefore about **three** observations, and
plausibly one story: large, liquid, stable stocks outperformed over this
window. Counting them as seven would overstate the evidence in the direction
that flatters.

`make ic ALL=1` now prints that arithmetic automatically
(`features/independence.py`), so it cannot depend on someone remembering to
check.

| feature | mean IC | t | reading |
|---|---|---|---|
| low_volatility | +0.063 | +5.78 | cluster: stability |
| illiquidity_amihud | +0.043 | +5.69 | cluster: liquidity |
| momentum_12_1 | +0.052 | +5.40 | cluster: momentum |
| max_drawdown | +0.063 | +5.30 | cluster: stability |
| turnover_liquidity | +0.034 | +4.97 | cluster: liquidity |
| price_to_52w_high | +0.059 | +4.82 | cluster: stability |
| small_size | −0.043 | −4.74 | cluster: liquidity (inverted) |
| momentum_6_1 | +0.025 | +2.89 | cluster: momentum |
| volume_trend | +0.010 | +2.39 | weak |
| reversal_1m | +0.016 | +2.16 | weak |

`small_size` scoring **−4.74** is worth noting: the sign says *larger* stocks
did better, which is the opposite of the documented long-run size premium and
is exactly what a 2023–2026 large-cap-led market looks like. It was included
as a deliberately weak proxy and it behaved like one.

`momentum_12_1` — buy what has been rising for a year — scored a
t-statistic of **+5.40**, positive in each of 2024, 2025 and 2026.

**This is a sanity check, not a discovery.** Twelve-month momentum is among
the most documented effects in global equities; finding it in Indian data is
evidence the harness works. If it had come out flat I would have suspected
the harness before the market.

Three reasons to discount the number even so, all printed by the tear sheet
itself rather than left for the reader to remember:

1. **The periods overlap.** At a 21-day horizon, cross-sections five days
   apart share most of their return window, so the t-statistic is inflated by
   roughly the square root of that overlap. It is a screen, not a test.
2. **No costs.** A signal that ranks stocks well can still lose money after
   brokerage, STT, stamp duty and impact. That is Sprint 9, and it kills more
   signals than IC does.
3. **Ten features chosen by someone who already believed in them** will
   produce several positive scores by construction. The trial counter exists
   so this cannot be quietly forgotten later.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: all green, 598 tests
```

```bash
make ic FEATURE=momentum_12_1
```

Expected: a tear sheet in about 75 seconds — mean IC, t-statistic, hit rate,
a per-year breakdown, an explicit verdict line, and the overlap caveat. The
per-year table is the part worth reading: a signal that worked in one year and
nowhere else has a flattering average and an obvious shape here.

```bash
make ic          # lists the ten features and the trial count
```

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| The panel covers 2023–2026, not 2015–2026 | 892 of ~2,870 trading days. Extending is `make build-panel FROM=2015-01-01`, purely a B2 budget question, and the panel is cached and resumable | whenever the budget allows |
| No fundamental features | The screener.in data is per-company snapshots rather than a point-in-time series, so using it would need a knowledge_time per field that we do not have. Left out rather than used carelessly | needs a bitemporal fundamentals loader |
| No factor neutralisation | The assigned reading covers it and the harness does not do it. A raw IC partly measures exposure to size and liquidity rather than the feature itself | Sprint 8.5 or before any multi-feature work |
| `small_size` is a poor proxy | Price, not market capitalisation — the share count is not in the bhavcopy. Deliberately included and labelled | needs shares outstanding |

## What I could not verify

- **Whether any of this survives costs.** Nothing here has met a cost model.
  My expectation is that the higher-turnover signals (reversal, volume trend)
  will not.
- **The true significance of the t-statistics.** The overlap correction is
  described but not applied; doing it properly is part of Sprint 13's battery.
- ~~Whether the ten features are independent.~~ **Measured: they are not.**
  Ten features are about three findings; see the table above. This was the
  single most important thing the sweep revealed and it would have been easy
  to miss by reading only the per-feature sheets.

## Decisions I need from you

1. **Extend the panel to 2015 now, or leave it at 2023?** Option A: extend —
   ~1,980 more B2 downloads, one run, and every future IC covers eleven years
   including a crash and a recovery. Option B: leave it; three years is enough
   to develop against and the budget stays free for other work.
   **My recommendation: A, next session.** Three years of Indian equities is
   almost entirely a bull market, so a momentum signal is being measured in
   the regime that flatters it most. That is a real limitation of every number
   in this review.

2. **Add factor neutralisation before or after the cost model?** Option A:
   before — neutralise size and liquidity so an IC measures the feature rather
   than its exposures. Option B: after, since costs kill more candidates.
   **My recommendation: A.** Neutralisation can turn a positive IC negative,
   so doing costs first risks carefully costing a signal that was never there.

## Reading added for you

- **Information Coefficient and factor neutralisation** (MUST, 40 min) —
  already on your list for this sprint. The first half is now concrete in
  `src/eulerlab/features/ic.py`; the second half is the gap named above, and
  worth reading before deciding question 2.

## Next sprint

Sprint 9 — the cost model. India-specific: brokerage, STT including on
exercise, stamp duty, GST, exchange fees, slippage and impact, verified
against 20 of your real contract notes to the paisa. It is the filter that
kills most of what IC lets through.
