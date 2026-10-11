# 071 — Two pure intraday papers, coded for NSE hours and run on NIFTYBEES

**Question.** Operator, 2026-10-11: "fetch 2 pure intraday strategy paper, code
it and backtest on Indian market". Which two published intraday strategies are
not already in the library, can be read in full, and survive Indian costs?

## Sources, fetched 2026-10-11

| Source | URL | Read |
|---|---|---|
| Gao, Han, Li, Zhou, "Intraday Momentum: The First Half-Hour Return Predicts the Last Half-Hour Return", working paper, first draft March 2014, **version December 2015** (published as "Market Intraday Momentum", *Journal of Financial Economics* 2018) | https://c.mql5.com/forextsd/forum/173/intraday_momentum_-_the_first_half-hour_return_predicts_the_last_half-hour_return.pdf (a third-party copy of the working paper; SSRN 2440866) | **In full**, 44 pages. The published JFE version was not read and may differ |
| Zarattini, Aziz, Barbon, "Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)", first version 10 May 2024, **version 3 February 2025**, Swiss Finance Institute paper 24-97 | https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content (University of St. Gallen repository). SSRN 4824172 returned 403 | **In full**, 43 pages. `docs/RESEARCH/papers/README.md` had this as "not retrievable and deliberately not coded"; it is retrievable from the university |
| Zerodha, auto square-off timings | https://support.zerodha.com/category/trading-and-markets/trading-faqs/market-sessions/articles/intraday-auto-square-off-timings | Page read. Equity intraday is squared off at **15:25** (15:12 for stocks in the Closing Auction Session, 15:26 for F&O contracts); ₹50 + GST per order squared off; "may adjust these timings" |
| Zerodha, SEBI's Closing Auction Session | https://support.zerodha.com/category/trading-and-markets/trading-faqs/general/articles/closing-auction-session | Page read. From **3 August 2026**, phase 1, F&O stocks stop continuous trading at 15:15 and close in an auction. The page does **not** say whether ETFs are included |

Not found: SEBI's or NSE's own circular for the Closing Auction Session (only
the broker's summary was read); whether NIFTYBEES may be sold short intraday
at every broker.

## What the papers say

**Gao et al.** S&P 500 ETF, 1993-2013. `r1` is the return from the previous
day's close to 10:00 (so it includes the overnight gap); `r12` is 15:00-15:30;
`r13` is the last half-hour. Regressing `r13` on `r1` gives R² 1.6%; on both,
2.6%. Timing rule (eq. 4): at the start of the last half-hour go long if `r1 >
0`, short otherwise, close at the close. Reported: 6.67% a year, standard
deviation 6.19%, Sharpe 1.08, success rate 54.37%. On `r12`: 1.77%, Sharpe
0.29. On both (trade only when they agree): 4.39%, success 77.05%. After the
bid-ask spread at 15:30 (2001 onward): 4.46% a year on `r1`.

**Zarattini et al.** SPY, May 2007 to early 2024, one-minute bars. The Noise
Area at minute HH:MM is `max(open, previous close) × (1 + σ)` above and
`min(open, previous close) × (1 − σ)` below, where σ is the average of
`|close at HH:MM / open − 1|` over the previous 14 days. Long above, short
below, decided only at HH:00 and HH:30, flat at the close, 100% of equity.
Base model (hold until the opposite band): Sharpe 0.61, 6.2% a year. Stop at
the current band or VWAP, whichever is nearer: Sharpe 1.24, 9.7% a year, hit
ratio 43%. With exposure scaled to 2% daily volatility, up to 4x: Sharpe 1.33,
19.6% a year. Costs: $0.0035 a share commission and $0.001 slippage.

## What had to change for India

- **Clock.** 09:15-15:30. First half-hour 09:15-09:45, last 15:00-15:30,
  decisions every 30 minutes from the open.
- **Exit.** A short cannot be held past the 15:25 square-off. Each rule is run
  with the published exit (the close) and a tradable one (the 15:24 open).
- **Instrument.** NIFTYBEES, the Nifty 50 ETF: 475,605 one-minute bars,
  2021-08-20 to 2026-10-08, 1,264 normal sessions. Ten special sessions
  (Muhurat, Saturday drills) are skipped.
- **Costs.** `costs.router` at NSE intraday rates: **4.0 bps of traded value
  per round trip** on ₹10 lakh, of which STT on the sale is 2.5. Plus 1 bp a
  side slippage (A-052).
- **Size.** 1x. The 4x volatility-scaled variant is not run: leverage is not a
  signal.

## Two things found in the data, before any result

**1. NIFTYBEES's first print is not a price.** The 09:15 open is on average
71 bps above the first minute's close (median 43, 95th percentile 311). The
overnight gap measured to that print correlates 0.21 with the Nifty 50's own
gap; measured to the first minute's close it correlates 0.89. Research 066
found the same on daily data. So every rule here takes the first minute's
*close* as the day's open. Run on the raw print, the noise-area rule saw 727
"down" days against 216 "up" and traded 364 times; on the corrected anchor the
days are balanced (384 up, 349 down) and it trades 1,227 times. **The first
run of this note was wrong for that reason and is not reported.**

**2. The last bar is not the close.** NIFTYBEES's 15:29 close is on average
4.7 bps above the exchange's official close (mean absolute gap 7.6 bps), and
that minute moves 4.3 bps against 2.2 for an ordinary one. Measured to the last
bar, the last five minutes appeared to reverse the day's move (t = −3.3);
measured to the official close the effect is zero (t = 0.00). "Previous close"
and the published exit therefore use the bhavcopy close. That close is a
30-minute volume-weighted price, so a return measured to it shares prices with
the 15:00 mark; the regression below uses the 15:24 traded price instead.

## Results, `make intraday-papers`, ₹10 lakh

Does the first half-hour predict the last (15:00 to 15:24)?
`r1`: slope −0.005, t −0.54, R² 0.02%. `r12`: slope 0.044, t 1.41, R² 0.16%.
n = 1,263. **Nothing**, against the paper's R² of 1.6%.

Sharpe ratios; "net" is after charges and slippage. Tradable exit.

| Rule | Trades | Gross | After charges | Net | Net total | Max drawdown | Gross bps / trade |
|---|---|---|---|---|---|---|---|
| Gao, `r1` | 1,263 | 0.26 | −3.41 | −5.26 | −52.8% | −52.9% | 0.27 |
| Gao, `r12` | 1,263 | 0.20 | −3.44 | −5.29 | −53.0% | −53.2% | 0.20 |
| Gao, both agree | 646 | 0.37 | −2.42 | −3.76 | −30.2% | −30.5% | 0.50 |
| Noise area, opposite-band stop | 856 | 0.73 | −0.30 | −0.83 | −25.0% | −30.9% | 2.63 |
| Noise area, band + VWAP stop | 1,227 | **1.58** | −0.44 | −1.44 | −30.8% | −34.6% | 2.96 |
| Buy and hold NIFTYBEES, no costs | | 0.63 | | | +43.1% | −16.1% | |

The published exit gives the same picture (gross Sharpe 0.13, 0.39, 0.41, 0.85,
1.54; net totals −53.9%, −52.2%, −30.4%, −22.4%, −31.6%).

Before and after 2024-01-01, gross Sharpe, tradable exit: Gao `r1` 0.31 / 0.20;
`r12` 1.53 / −1.28; both 1.47 / −0.76; noise area opposite band 0.72 / 0.76;
band + VWAP **1.63 / 1.54**.

## Findings

1. **Gao's intraday momentum is not in NIFTYBEES.** The first half-hour does
   not predict the last. The timing rule earns 0.3 bps a trade before costs and
   pays 4 in charges, every day. Dead.
2. **The noise area has a gross edge and it is stable**: Sharpe 1.58 before
   costs, 1.63 before 2024 and 1.54 after, about 3 bps a trade, over 615
   long and 612 short trades. That is above the paper's own 1.24 at 1x (which is net of far
   smaller costs).
3. **Indian intraday charges are larger than that edge.** 3 bps earned, 4 bps
   charged, 2 more assumed in slippage: −31%. STT on the sale alone is 2.5 bps.
   On the cash ETF this strategy cannot be traded at a profit.
4. Nothing here is promoted, and nothing was tuned. No trial was spent.

## Decision

Both recorded as `rejected` for NIFTYBEES cash (H-0005, H-0006). The noise-area
signal is the first intraday rule in this project with a stable gross edge;
whether a cheaper instrument carries it is T-4039, and needs minute data for
the Nifty future that this project does not have.

## Confidence

High that both lose after costs: the cost is measured from the project's cost
model and is larger than the gross edge in every run. Medium on the size of the
gross noise-area edge: one instrument, five years, fills assumed at the next
minute's open with no queue, and the anchor is a choice made after seeing the
first print was unusable (the choice is the one research 066 already implied).

## Open questions

- Does the noise-area edge survive on Nifty futures, where the round trip is
  cheaper? No minute data for futures is landed (T-4039).
- Do the existing intraday signals (`orb_breakout`, `orb_in_play_in`, Wang's
  breakout) read the 09:15 print as the opening range's high on ETFs? They use
  the first bars' high and low (T-4040).
- Is NIFTYBEES in the Closing Auction Session? If it joins, continuous trading
  ends at 15:15 and the last half-hour as defined here no longer exists
  (A-053).
