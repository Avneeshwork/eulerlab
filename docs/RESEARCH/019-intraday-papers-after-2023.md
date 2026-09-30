# 019 — Intraday strategy papers published after 2023

**Question.** The operator asked for ten intraday research papers released after
2023, coded onto this platform. What exists, what is precise enough to code, and
what does this platform's data and engine actually permit?

## Sources

| Paper | Where | Fetched | Full text? |
|---|---|---|---|
| Mesfin (2026), *Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures: A Systematic Falsification Study* | arXiv:2605.04004 (v1 2026-05-05, v2 2026-07-13) — https://arxiv.org/abs/2605.04004 | 2026-08-22 | **Yes**, PDF extracted in full |
| Zarattini, Barbon & Aziz (2024), *A Profitable Day Trading Strategy For The U.S. Equity Market* | SSRN 4729284 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284 | 2026-08-22 | **No** — SSRN returned 403. Rules recovered from the publisher's own summary (https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/) and a third-party reproduction (https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/) |
| Zarattini, Aziz & Barbon (2024, rev. 2025-09-22), *Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)* | SSRN 4824172 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172 | 2026-08-22 | **No** — SSRN 403, university mirror returned 405. Mechanics recovered from a third-party review (https://quantmacro.substack.com/p/paper-review-an-effective-intraday) |
| Maróy (2025), *Improvements to Intraday Momentum Strategies Using Parameter Optimization and Different Exit Strategies* | SSRN 5095349 | 2026-08-22 | **No** — 403. Only the abstract-level claim was obtained |

## What could not be found

Stated explicitly, because absence of evidence is a finding:

- **SSRN blocks automated fetching.** Three of the four papers above are SSRN
  working papers and all returned 403. For Zarattini's ORB the rules were
  recovered from two independent secondary sources that agree, which is
  usable. For *Beat the Market* the **noise-boundary formula itself was not
  obtained** — only that it is a volatility cone from historical intraday
  returns, entered on a break by a multiplier N, trailed on VWAP, flat at the
  close. That is not enough to code faithfully, and coding it from a guess
  would produce a result attributed to a paper that did not specify it.
- **No limit-order-book paper is implementable here.** The 2024–2026 intraday
  literature is dominated by deep learning on LOB data (mid-price prediction,
  order-flow imbalance). This platform has **minute OHLCV bars, not order
  book**. The operator has offered to fetch missing data; LOB history is the
  one case where that is a large undertaking rather than a download, and it is
  called out separately below.
- **Ten distinct papers were not reached in this pass.** Four were verified to
  the level this repository requires. The signals coded below come from those
  four — chiefly Mesfin, which enumerates fourteen families with exact rules.

## Findings

### Mesfin (2026) is the most useful paper for this platform, because it fails

947 trading days of MNQ futures, 2021–2025, five-minute bars. Fourteen signal
families tested against five criteria: walk-forward validation, t ≥ 2.0, at
least 30 trades, positive net return after two-point round-trip friction, and
consistency across years. **None passed.** Maximum gross return across every
family was 1.05–1.50 points at the best horizon, against a 2.0-point friction
cost.

That is the single most valuable prior this repository could be handed. A
strategy library ordinarily arrives with a positive prior from a published
result and the noise bar's job is to argue it down. Here the prior is already
negative and *measured*, so a positive result on our data is immediately
suspect — which is the correct starting posture and one we normally have to
manufacture.

The per-family results, verbatim from the paper's tables:

| Family | Best variant | N | Mean net (pts) | t | Verdict |
|---|---|---|---|---|---|
| Opening range breakout | Long, bar+15 | 447 | +2.82 | 1.50 | FAIL (year instability) |
| Asia session expansion | 2.5×, bar+6 | — | −0.94 | −0.90 | FAIL |
| Asia liquidity grab | fade | 6,442 | −2.20 | −14.12 | FAIL |
| Gap fill fade | 09:45 entry | ~240/yr | −1.31 | −0.32 | FAIL |
| Gap continuation short | Kalman v>2.5 | 22 | +14.52 | +3.23 | FAIL — N<30 |
| Volume spike momentum | up spike | 2,119 | −1.94 | +0.07 | FAIL |
| Volume dry-up exhaustion | up | 1,060 | −2.42 | −0.92 | FAIL |
| VVG volatility classifier | reversal | 289 | +1.37 | +0.86 | FAIL |
| Event-day trend | RTH sample | 993 events | — | 0.38 | FAIL |
| MGC OU mean reversion | 5-min, 2.0σ | 154 | −2.19 | −2.19 | FAIL |

Two findings inside it are worth more than the headline:

1. **The Asia expansion signal is significantly wrong, not merely unprofitable**
   (t = −10.96 at bar+1). The paper's explanation is a timing problem, not a
   modelling one: the directional burst is real but *entirely consumed inside
   the expansion bar*, so a bar-close system entering on the next bar captures
   the post-exhaustion reversal. Momentum that exists inside a bar cannot be
   reached by bar-close execution. That generalises well beyond this signal.
2. **The dominant failure mode is one good year masking flat ones.** ORB long
   returns −1.42 (2022), +2.43 (2023), +7.04 (2024). The 2024 figure would pass
   in isolation. The VVG continuation entry does the same: t = 2.07 in 2024,
   negative either side.

The two positive controls (RTH Confluence, London Signal B; t = 5.83 and 5.15,
permutation p < 0.001) both use **GMM regime classification and hold 60–75
minutes**, not 5–30. The paper's structural claim is that on five-minute bars
the gross edge competes down to roughly the friction cost of the marginal
participant, and that reaching past it requires either a longer horizon or
information not in OHLCV.

### Zarattini, Barbon & Aziz (2024) is codeable and its rule is unambiguous

Recovered consistently from two independent secondary sources:

- Opening range: first **5 minutes** (09:30–09:35 ET), its high and low.
- Direction: long if the opening range closes above its open, short if below.
- Entry: stop order at the opening-range high (long) or low (short).
- Stop loss: entry ∓ 1.4 × ATR(14, daily).
- Exit: at the close, or the stop.
- Universe: top 1,000 liquid US equities, price > $5, ATR > $0.50.
- **Selection is the strategy.** Trade only "stocks in play": first-5-minute
  volume divided by the mean first-5-minute volume of the prior 14 days,
  greater than 1. The publisher's own summary reports Sharpe 2.81 and >1,600%
  over 2016–2023 on the top-20 basket; a third-party account emphasises that
  the plain ORB is weak and the relative-volume selection does almost all the
  work.

**This directly contradicts Mesfin on ORB**, and the contradiction is
informative rather than awkward: Mesfin tests ORB on a *single* index future
with no cross-sectional selection step; Zarattini's result is a *selection*
result across 7,000 names. The two are consistent if the edge lives in picking
which instrument to apply ORB to, not in the breakout.

## Decision

Code the Mesfin families and the Zarattini ORB against this platform's intraday
surface, on Indian equity minute bars (420 symbols in B2) and crypto minute
bars (20 pairs), and treat every one of them as **expected to fail**. Record
each as a hypothesis with the published result as its prior, so a positive
result here has to argue against a measured negative rather than against
nothing.

Do **not** code *Beat the Market*: its noise boundary was not obtained, and a
guessed formula attributed to a named paper is worse than an absent strategy.

**Confidence.** High on Mesfin — full text, exact tables. Medium on Zarattini
ORB — two independent secondary sources agreeing, primary blocked. Low on the
other two; neither is coded.

## Open questions

- Does the Mesfin friction ceiling transfer to Indian equities? Costs here are
  different in kind (STT, stamp duty, a percentage rather than a fixed
  point-spread), and the "2 points on MNQ" ceiling has no direct analogue. This
  is the first thing running these signals here will measure.
- Zarattini's selection step needs a *relative volume* screen across a
  cross-section at 09:20 IST. The intraday surface scans symbol by symbol and
  has no cross-sectional step, so this is the one structural addition the
  paper requires.
- LOB data would open the largest branch of the recent literature. That is a
  vendor purchase or an exchange feed, not a download.
