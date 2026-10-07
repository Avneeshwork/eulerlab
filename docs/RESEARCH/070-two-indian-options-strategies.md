# 070 — Two Indian index-options strategies on daily Nifty data

**Question.** Operator, 2026-10-07: "research on 2 Indian options strategy and
implement based on data we have". Which published Indian options strategies
can be tested on end-of-day data, and do they survive costs?

## Sources, fetched 2026-10-07

| Source | URL | Read |
|---|---|---|
| Bangur, P. (2020), "Strangle to resuscitate: evidence from India", *Journal of Investment Strategies* | https://www.risk.net/journal-of-investment-strategies/7721271/strangle-to-resuscitate-evidence-from-india | Abstract only (paywalled). Nifty 2007-2019, monthly; short strangle beats long at every "leg"; the third leg has the lowest risk and highest return. Legs, strikes and rules are not stated |
| Aggarwal, N. (2011), covered call on S&P CNX Nifty, *Asia-Pacific Business Review* | found via search; publisher page not opened | From the search summary only: Oct 2005 - Sep 2010; ATM, 2%/5% ITM, 2%/5% OTM calls of one, two and three months; buy the index at the close and sell the call, square off at the next close; 5% ITM beats the index on every measure. **The rule was taken from a search snippet, not the paper** |
| Other candidates seen | https://osuva.uwasa.fi/handle/11111/19466 (straddles, negative Sharpe); NSE working paper 9 on India VIX | Not used |

Not found: any open full text of either paper.

## Data

`make nifty-options`: every Nifty option and future from the F&O bhavcopy,
2015-01-01 to 2026-10-07, 2,891 of 2,903 days (12 archives failed to download
and are retried by re-running). Spot is the Nifty 50 close from
`index_history.jsonl`; expiries are the 144 confirmed monthly expiries.
A contract fills at its traded close; one that did not trade is skipped.

## Rules as run

- **Short strangle**: the first session after each monthly expiry, sell the
  call and the put *k* x 2% out of the money (k = 1, 2, 3; A-049), hold to
  expiry, settle at intrinsic against the Nifty close. Return on margin of
  15% of notional (A-050).
- **Covered call, daily** (the paper's rule): near-month future bought and the
  same-month call nearest 5% in the money sold at the close; both closed at the
  next close. Return on full notional.
- **Covered call, monthly**: the same pair opened after each expiry, held to expiry.
- **Benchmark**: the near-month future alone, month to month.

Costs through `costs.model`: STT on premium sold and on in-the-money expiry
(notional before 2019-09, intrinsic after), stamp, exchange, SEBI, GST, ₹20
per order. Units are continuous, not lots (S-039).

## Results, after costs, ₹10 lakh

Sum of monthly returns (not compounded: a strategy that can lose more than its
capital in one month cannot be compounded meaningfully).

| Strategy | Months | Sharpe | Sum, all | Before 2024 | From 2024 | Worst month | Costs |
|---|---|---|---|---|---|---|---|
| Strangle 2% OTM | 138 | -0.11 | -77% | -85% | +8% | -120% (Mar 2020) | ₹2.85L |
| Strangle 4% OTM | 138 | -0.07 | -40% | -37% | -3% | -115% (Mar 2020) | ₹1.80L |
| Strangle 6% OTM | 136 | 0.10 | +43% | +50% | -7% | -104% (Mar 2020) | ₹0.95L |
| Covered call, daily | 2,860 days | -1.62 | -79% | -53% | -27% | -7% (a day) | ₹10.1L |
| Covered call, monthly | 138 | -0.07 | -5% | +1% | -6% | -17% (Mar 2020) | ₹0.83L |
| Nifty future, monthly | 138 | 0.17 | +33% | +55% | -22% | -22% (Mar 2020) | ₹0.09L |

## Findings

1. **No short strangle is worth trading.** The widest (6%) is the only one
   that made money, about 3.9% a year on margin, and it lost more than its
   whole margin in March 2020 and 42% in March 2026. Bangur's ordering (the
   widest leg is best) holds; his profitability does not, after costs and with
   2020 in the sample.
2. **The paper's daily covered call is destroyed by costs.** Four orders a
   day cost ₹10 lakh over eleven years on ₹10 lakh of capital.
3. **Held monthly, the covered call is a calmer, poorer Nifty**: about flat
   against the future's +33%, with a shallower worst month (-17% vs -22%).
   Aggarwal's 2005-2010 outperformance is not reproduced on 2015-2026.
4. Nothing approaches the noise bar of 2.99.

## Decision

Neither strategy is registered for deployment. The code stays as the options
backtesting path (`options/strategies.py`), which did not exist before.

**Confidence:** high that daily covered calls lose to costs; moderate on the
strangle, whose legs are assumed and whose margin rate is not measured.
