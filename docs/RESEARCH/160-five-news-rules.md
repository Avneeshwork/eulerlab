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
