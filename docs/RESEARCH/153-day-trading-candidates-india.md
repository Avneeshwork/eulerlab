# 153 — Day-trading candidates for the Indian market, after twenty dead ones

**Question.** Operator, 2026-11-05: "research on some day trading strategy for
indian market". About twenty intraday rules have already been screened here
(research 019, 071, 072, 075, 076, 077, 084, 087-089, 103, 107, 108, 111, 112)
and every one died after costs. Which ideas are left whose profit per trade
could plausibly exceed the cost of the trade, and can our data test them?

**Status.** Rules pre-registered as H-0040 and H-0041 and committed before any
backtest. Results are added below the line "Results" after the runs.

## The bar a day trade must clear

The cost of a round trip, from `costs/schedule.py` (rates by date) plus the
screens' 2 bps a side of slippage:

| Instrument | Main statutory charge | Round trip, as the screens model it |
|---|---|---|
| Cash stock, intraday | STT 0.025% on the sell side | about 14.5 bps (research 112: 8.06 gross became -6.53 net) |
| Stock or index future | STT 0.02% sell to 2026-03-31, **0.05% from 2026-04-01** (Budget 2026) | about 9 bps before April 2026, about 12 after |
| Option (premium) | STT 0.0625% → 0.10% (2024-10-01) → 0.15% (2026-04-01) of premium sold | small against the premium, large against the index move |

Futures are no longer the cheap way to day-trade: since April 2026 their STT
is twice a cash stock's. The best rule screened so far (overnight reversal,
H-0020) made 8 bps gross. **A new idea is worth testing only if the source
suggests well over 15 bps a trade.**

SEBI found 71% of individual intraday traders in the cash segment lost money
in FY23, and 80% of those making over 500 trades a year
([SEBI press release, 24 Jul 2024](https://www.sebi.gov.in/media-and-notifications/press-releases/jul-2024/sebi-study-finds-that-7-out-of-10-individual-intraday-traders-in-equity-cash-segment-make-losses_84948.html),
fetched via search 2026-11-05). That is the base rate.

## Sources, searched and fetched 2026-11-05

| # | Idea | Source | What it says | Read |
|---|---|---|---|---|
| 1 | Fade the results gap | Liu, Hope and Hu (2023), "Earnings announcements in China: Overnight-intraday disparity", *J. Corporate Finance* 82, 102471 — [IDEAS](https://ideas.repec.org/a/eee/corfin/v82y2023ics0929119923001207.html) | Overnight returns react strongly and consistently to earnings; the following intraday session trades **against** both the news and the overnight move; only the overnight part predicts later returns | Abstract page fetched; the full paper (exact clock times) not read |
| 1 | (support) | Lou, Polk and Skouras (2019), "A tug of war: Overnight versus intraday expected returns", *JFE* 134(1), 192-213 — [LSE](https://researchonline.lse.ac.uk/id/eprint/87481) | Profits of a strategy come from one half of the day and reverse in the other; competing clienteles | Search summary and bibliographic record |
| 2 | Sell the expiry-day straddle | FlashAlpha, "Are 0DTE straddles overpriced?" — [article](https://flashalpha.com/articles/are-0dte-straddles-overpriced-193-spy-sessions-data-study) | 193 SPY Wednesdays 2022-2026: 10:00 implied 1σ held the close 71.0% of days (68.3% fair); median realized/implied 0.589 vs 0.674 fair; no P&L, no costs; 9 Apr 2025 moved 2.5× implied | Fetched |
| 2 | (warning) | CAIA, short straddles show profits more often until the losses come — [CAIA](https://caia.org/node/7160) | Win rate is misleading for short premium | Search summary |
| 3 | Index-inclusion close pressure | Joshipura and Janakiramanan (2015), Nifty reorganisations — [IDEAS](https://ideas.repec.org/a/ids/afasfa/v5y2015i1p21-36.html); Parthasarathy (2010) — [IDEAS](https://ideas.repec.org/a/mth/ajfa88/v2y2010i2p55-80.html) | Volume and price rise on the effective day and fail to sustain (price pressure); Parthasarathy finds permanent gains instead | Search summaries |
| 4 | F&O ban entry | Broker explainers only, e.g. [ICICI Direct](https://www.icicidirect.com/ilearn/stocks/articles/future-and-options-ban-impact-on-stock) | Claims prices "usually" fall in a ban; no data | Search summary |
| 5 | Same half-hour seasonality | Heston, Korajczyk and Sadka (2010), *J. Finance* — [arXiv 1005.3535](https://arxiv.org/abs/1005.3535) | Half-hour returns continue at daily multiples for 40 days, US stocks | Search summary |
| 6 | First half-hour predicts last | Gao, Han, Li and Zhou (2018), *JFE* | SPY: 6.3% a year gross, about 2.5 bps a trade | Already tested on NIFTYBEES (research 071, dead) |
| 7 | Magnet effect near circuit limits | Mohamad and Sifat (2018), *J. Behav. Exp. Finance* — [IDEAS](https://ideas.repec.org/a/eee/beexfi/v20y2018icp1-8.html) | Malaysia: weak magnet, comparable repellent effect | Search summary |
| 8 | Pre-open auction | Acharya and Gaikwad (2014), *Cogent Econ. & Finance*; Sharma and Gupta (2015), *Indian J. Finance* | Price discovery at the open, daily data; no trading rule | Search summaries |
| 9 | Closing price = last-30-minute VWAP | SEBI consultation on a closing auction (via [caalley.com](https://caalley.com/exp_drafts/1733395855211.pdf), not SEBI's own site) | On MSCI rebalance days the last half hour was 3.3× as volatile as 09:15-14:30; on other days similar | Search summary; not verified on sebi.gov.in |
| 10 | Fast-crash recovery | Jagannathan et al. (2022), *J. Financial Markets* — [NBER w24098](https://www.nber.org/papers/w24098) | NSE 2006, one stock, order-book data: mutual funds slowly buy crashes back | Search summary |

**Not found** (absence is a finding): no peer-reviewed study of NSE intraday
returns around F&O ban entry, around the closing VWAP window, near circuit
limits, or of Nifty expiry-day straddles; no Indian replication of Gao et al.
or of Heston-Korajczyk-Sadka; the SSRN review "Intraday Scalping on the NSE
after the 2025-26 cost and algorithmic-trading regime changes" (abstract 7547298)
returned 403 and was not read.

## The filter

| Idea | Edge likely > costs? | Data here? | Decision |
|---|---|---|---|
| 1 Results-gap fade | Yes: results gaps are often 2-10%, a fade of even a fifth of that is 40+ bps | Results timestamps 2021-07 to 2024-12 (23,306 rows, 14,655 outside hours); minute bars for 416 F&O stocks to 2024-11-29 | **Test: H-0040** |
| 2 Expiry-day short straddle | Yes, if the variance premium exists: costs are a few % of premium | F&O bhavcopy OPEN and settlement for every Nifty option, 2019 on, in B2 | **Test: H-0041** |
| 3 Index-inclusion close | Possibly, but about 10 events a year | No history of index changes stored | Drop: sample too small to judge |
| 4 F&O ban entry | Unknown, no evidence | Ban list only from 2025-10-30, after the research window | Hold: needs a backfill of NSE's `fo_secban` archive for 2021-2024 (your call) |
| 5 Half-hour seasonality | No: US effect is a few bps a half hour | Yes | Drop on the cost bar |
| 6 Gao intraday momentum | No: about 2.5 bps a trade | Tested | Drop (research 071) |
| 7 Magnet effect | Unknown; F&O stocks have no fixed bands | Only non-F&O stocks have bands | Drop |
| 8 Pre-open | No rule | — | Drop |
| 9 Closing VWAP | No rule | — | Drop |
| 10 Crash recovery | No rule, one stock in 2006 | — | Drop |

Two survive, not the three to six hoped for. The rest fail on cost, data or
evidence, and testing them anyway would spend effort on ideas this note
already expects to die.

## The rules, fixed before running

**H-0040 — fade the results gap.** Event: the first NSE disclosure of a
stock's results after the previous session's 15:30 and before 09:15. Signal:
prior close to the 09:19 close. If the move is at least 2% either way, trade
against it at the 09:20 open and close at 15:10. ₹1 lakh a trade, at most ten a
day, earliest disclosure first; 2 bps slippage a side; cash-intraday costs on
the day. July-December 2022 excluded (NSE did not label results then,
`nse_earnings_announcements.INCOMPLETE`). Window 2021-08-20 to 2024-11-29.
Built on the india-five cache, which already holds every stock-day's 09:19
move and 09:20/15:10 fills (`overnight_reversal_screen.extract`).

**H-0041 — sell the expiry-day straddle.** Each weekly Nifty expiry day from
the first weekly expiry (February 2019) to 2024-11-28: strike = Nifty 50 open
rounded to the nearest 50; sell that strike's call and put at their bhavcopy
OPEN less 1 index point each; hold to the exchange settlement price. ₹10 lakh
of Nifty notional in continuous units (S-039), options costs on the day; a
short leg pays no exercise STT. A day where either leg has no OPEN is skipped.

Both are judged the same way: net mean per trade, net Sharpe, worst trade,
maximum drawdown, and the two halves (before 2024 and 2024). A rule must be
positive net in both halves to be worth taking to you. Screening only: no trial
is spent and neither is judged by the gate.

## Confidence

Low for both. H-0040 comes from China, where intraday trading works differently;
H-0041 rests on a vendor study of SPY and on the general variance premium.

## Open questions

- Backfill the F&O ban list for 2021-2024 so idea 4 can be tested (the NSE
  archive `fo/sec_ban/fo_secban_DDMMYYYY.csv` is the source `nse_reports`
  already uses)?
- The full Liu-Hope-Hu paper, for the exact intraday window they measure.

## Results (run 2026-11-05, after the rules were committed in `a4548e9`)

`make results-gap-fade` → `data/derived/results_gap_fade.json`;
`make expiry-straddle` → `data/derived/expiry_straddle.json`. No trial spent.

| Rule | Trades | Gross a trade | Net a trade | Net Sharpe | Worst trade | Max drawdown | Net before 2024 / 2024 |
|---|---|---|---|---|---|---|---|
| H-0040 results-gap fade | 1,249 (of 16,012 results mornings) | 6.47 bps | **-5.79 bps** | -0.32 | — | -14.5% | 2021 +, 2022 -, 2023 +, 2024 - (Sharpe 1.82, -1.22, 0.70, -1.18) |
| H-0041 expiry-day straddle | 299 expiries, none skipped | 8.79 bps of notional | **+6.96 bps** | **0.95** | -307 bps (2020-03-12) | -3.8% of notional | +6.53 bps, Sharpe 0.87 / +9.22 bps, Sharpe 1.38 |

**H-0040 is dead.** Fading a results gap earns 6.5 bps gross, the same size
as the dead overnight reversal (8 bps) and below the cost of a cash round trip.
The years alternate in sign. The Chinese result does not carry over at a
size that pays for the trade. Rejected; not re-run with another threshold.

**H-0041 is alive as a screen, not as a strategy.**
- Positive net in both halves, 64% of expiries won; it sold on average 108.5
  points of premium and paid back 96.5.
- The return is small on notional: 6.96 bps a week is about 3.6% a year on
  ₹10 lakh of Nifty exposure, with a Sharpe (0.95) just under the gate's noise
  bar of 0.98. Return on margin would be several times larger, and so would
  the loss on a bad day; margin is not modelled.
- The worst days are crash days: 12 Mar 2020 (-307 bps, Nifty 460 points
  below the strike), 16 Jun 2022 (-216), 15 Oct 2020 (-183). One such day takes
  about 44 average weeks to earn back.
- Fill risk is the main doubt. Each extra index point of slippage a leg costs
  1.31 bps, so the result survives up to about 5 more points a leg than the
  1 assumed. The bhavcopy OPEN is the first trade, not a price anyone was
  sure to get at 09:15.

**What it would take to go further** (operator decisions, nothing run):
1. Gate it as a strategy: one trial, judged on the gate's own bar.
2. Before that, check fills with minute option prices (FYERS expired-contract
   history, T-4285's login) for a sample of expiries.
3. Since 2024-11-20, lots are larger and expiry-day margins higher; from
   2025-09 the expiry moved to Tuesday. The holdout (from 2024-12-01) is the
   only test of whether it survived those changes, and it can be read once.
