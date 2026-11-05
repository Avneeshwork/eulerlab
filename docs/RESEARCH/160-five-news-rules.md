# 160 — Five intraday news rules from NSE corporate announcements

**Question.** Operator, 2026-11-06: "find next 5 strategy", and, asked whether
to move to multi-day holds after thirty-one intraday rules failed, "more
intraday". Cash stocks at 1x, minute bars.

**Status.** H-0072 to H-0076 pre-registered and committed before any run.
Results follow under "Results".

## A new input: company news, timed to the second

Every rule so far traded price, volume, calendar or option-market signals.
None used company news except results (H-0022, H-0040, H-0054). The NSE
corporate-announcements archive already landed for research 114
(`data/landing/nse_announcements`, 14 quarterly files, 2021-07 to 2024-12)
holds every filing, not only results, each with its NSE dissemination time.
Across all listed companies (not only F&O stocks), 2021-2024:

| Category | Filings | 09:20-14:30 |
|---|---|---|
| Press Release | 21,372 | 7,622 |
| Credit Rating | 5,243 | 1,334 |
| Acquisition | 3,441 | 683 |
| Buyback | 225 | 53 |
| Bagging/receiving of orders | 193 | 62 |

News moves a stock far more than an ordinary minute does, so the move after a
filing has a chance to exceed the 12.24 bps round trip that every price rule
fell short of.

## Sources, searched 2026-11-06

| Rule | Source | Read |
|---|---|---|
| H-0072-H-0074 | Jiang, Li and Wang (2021), "Pervasive underreaction: evidence from high-frequency data", *JFE* 141(2), 573-599 ([IDEAS](https://ideas.repec.org/a/eee/jfinec/v141y2021i2p573-599.html), [SSRN](https://papers.ssrn.com/abstract=2679614)) | Abstract: underreaction to firm news is widespread; a drift strategy earns abnormal returns after transaction costs; stronger when investors are distracted |
| H-0075 | Indian dividend event studies: Global Business Review 2021; Kumar (2017) ([RePEc](https://econpapers.repec.org/RePEc:eee:riibaf:v:39:y:2017:i:pa:p:327-337)) | Abstracts: positive abnormal returns right after cash dividend announcements; increases rise, cuts fall; some sectors differ |
| H-0076 | Indian buyback studies, e.g. IMFI 2024 ([businessperspectives](https://www.businessperspectives.org/index.php/journals/investment-management-and-financial-innovations/issue-462/announcement-effect-of-tender-offer-share-buyback-around-turmoil-period-evidence-from-india)), "Trading strategy using share buybacks: evidence from India" | Abstracts: significant abnormal returns on the announcement day (tender offers, NSE); some pre-announcement drift |

**Dropped:** orders and contracts (62 filings in hours across all companies,
far fewer among F&O stocks); qualified institutional placements (25 in hours).

## The rules, fixed before running

Kite minute bars of F&O stocks to 2024-11-29; ₹1 lakh a trade, 1x, at most ten
a day, earliest disclosure first; cash-intraday charges plus 2 bps a side.

1. **H-0072 press release follow.** Disclosed 09:20-14:30; a 1% move in the
   next five minutes is followed from the next open to 15:10.
2. **H-0073 acquisition or merger follow.** The same, for Acquisition and
   Amalgamation/Merger filings.
3. **H-0074 credit rating follow.** The same, for Credit Rating filings.
4. **H-0075 dividend.** Disclosed 09:20-14:30: buy at the next minute, sell at
   15:10.
5. **H-0076 buyback.** Disclosed in hours: buy at the next minute; outside
   hours: buy at the next session's 09:20 open; sell at 15:10.

Judged as before: positive net in both halves (before 2024, and 2024). No
trial spent.

## Confidence

Low to medium for H-0072, which has a large sample and a source that reports
profits after costs; low for the rest.

## Results (run 2026-11-06, after the rules were committed in `3be3d84`)

`make news-intraday` → `data/derived/news_intraday.json`. Among the 416 F&O
stocks, 2021-08 to 2024-11: 3,271 press releases, 322 credit ratings, 267
acquisitions or mergers, 301 dividends and 5 buybacks were filed between 09:20
and 14:30 (29 buybacks in all). 1x; no trial spent.

| Rule | Trades | Gross a trade | Net a trade | Net Sharpe | Before 2024 / 2024 (net Sharpe) |
|---|---|---|---|---|---|
| H-0072 press release follow | 206 | **-29.80 bps** | -42.06 bps | -1.22 | -0.70 / -2.39 |
| H-0073 acquisition follow | 12 | 26.75 bps | +14.43 bps | 0.14 | -0.13 / 0.80 |
| H-0074 credit rating follow | 3 | -154.53 bps | -166.78 bps | -0.85 | too few |
| H-0075 dividend day | 260 | 5.39 bps | -6.91 bps | -0.20 | -0.67 / 0.78 |
| H-0076 buyback day | 28 | 12.54 bps | +0.26 bps | 0.00 | 0.51 / -1.52 |

**None passes.**

- **News does not drift here; it reverses.** Of 3,271 in-hours press
  releases, 206 moved the stock 1% within five minutes, and following them lost
  30 bps gross a trade by 15:10. That is the opposite of Jiang, Li and Wang's
  underreaction, and the same as the results-in-hours rule (H-0022, -17 bps).
  On NSE's large stocks, a fast move on company news overshoots within the day.
- **Credit ratings and acquisitions rarely move these stocks** at all: 3 and 12
  filings reached the 1% bar.
- **Dividend and buyback days** earned 5 and 13 bps gross, below or at the
  cost; the buyback sample is 28 trades.

The fading of news moves is the one consistent pattern in research 153-160:
results in hours (-17 bps for following), the results-morning gap (+6.5 for
fading), press releases (-30 for following). It is not tested here as a rule,
because choosing its direction now would be choosing on these results; it would
need its own registration and data the rule has not seen.
