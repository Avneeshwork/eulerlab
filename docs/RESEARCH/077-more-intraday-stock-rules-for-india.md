# 077 — More intraday rules for Indian stocks: what the literature has

**Question.** Operator, 2026-10-13: "research on more intraday stock strategies
for indian stocks". Beyond research 076, which published intraday rules for
single stocks could be tested on the minute bars held here, and which are
worth a test?

**Nothing was coded or run for this note.** It is a reading list with a
recommendation.

## Sources, searched and fetched 2026-10-13

| Source | URL | Read |
|---|---|---|
| Baltussen, Da & Soebhag, "End-of-Day Reversal", working paper, **April 2025** | https://academicweb.nd.edu/~zda/EOD.pdf | PDF fetched, 55 pages. **Abstract, introduction, data and main result (sections 1-3.3) read.** The channel tests and the appendix were not |
| Heston, Korajczyk & Sadka, "Intraday Patterns in the Cross-section of Stock Returns", *Journal of Finance* 65(4), 2010; arXiv 1005.3535 | https://ar5iv.arxiv.org/html/1005.3535 | Read through an automatic summary of the full HTML text, not line by line. Table numbers quoted below come from that summary |
| Haendler, Heston, Korajczyk & Sadka, "The Intra-Day Stock Return Periodicity Puzzle", SSRN 5749704, November 2025 | https://papers.ssrn.com/ab_id=5749704 | **Search summary only.** Says the 2010 pattern persists out of sample |
| Della Corte, Kosowski & Wang, "Market Closure and Short-Term Reversal", November 2015 | summaries at https://www.cxoadvisory.com/technical-trading/overnightintraday-return-reversal-trading/ | **Not read.** Secondary summaries only. One quotes a Sharpe of 24 before costs, which is not believable as a tradable figure |
| Zarattini & Aziz, "Volume Weighted Average Price (VWAP): The Holy Grail for Day Trading Systems", SSRN 4631351, 2023 | https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/ | **Not read.** Authors' summary and third-party replications via search. Tested on QQQ and TQQQ, not on stocks |
| Rajvanshi, "Impact of Bulk Trades on Price Discovery in Equity Market", IIM Calcutta WPS 863, April 2021 | https://studentlive.iimcal.ac.in/sites/all/files/pdfs/wp_863.pdf | PDF fetched; abstract and introduction read. NSE bulk deals 2010-2019. **Daily, not intraday** |
| Agarwalla & Pandey, block trades on the NSE | https://nsearchives.nseindia.com/content/research/NSE_Proposal_216_Final_Paper.pdf (the likely file; not confirmed) | **Not read**: the fetch timed out. Known from a search summary only |
| Bag (2019), "Information content of stocks in call auction of shorter duration in emerging market", CJFA | https://apcz.umk.pl/CJFA/article/view/30366 | **Search summary only** |
| SEBI study of intraday trading by individuals in the equity cash segment, FY 2022-23, released 24 July 2024 | press coverage, e.g. https://www.business-standard.com/amp/markets/news/7-in-10-intraday-traders-in-equity-cash-suffered-losses-in-fy23-sebi-study-124072400975_1.html | **Press coverage only**; SEBI's own document was not fetched |

## What was not found

This is the main finding. Eighteen searches were run. Those for Indian evidence covered:
intraday momentum and reversal in single stocks, overnight against intraday
returns, intraday pairs trading, the pre-open auction, opening gaps, price
bands, block and bulk deals, earnings announcements, VWAP and Bollinger rules
on minute data, and the half-hour periodicity.

- **No reviewed paper was found that tests an intraday rule on NSE stocks
  with costs**, other than the ones already in research 076.
- No Indian replication of the end-of-day reversal or of the half-hour
  periodicity was found.
- No Indian study of opening gaps, intraday pairs, or intraday reactions to
  earnings was found. Broker pages describe them and test nothing.
- The Indian work on bulk deals and earnings is daily, not intraday.

So the candidates below are rules proven on US stocks. Testing one here is a
test of whether it carries over, not a replication.

## The candidates

**1. End-of-day reversal (Baltussen, Da & Soebhag 2025).** US stocks from
1993. Sort stocks on the return from the previous close to one hour before
the close. Skip half an hour. Over the last half-hour the losers rise and the
winners do not. Low-minus-high quintile: 3.78 bps a day value-weighted
(t 10.7), 6.38 to 6.86 equal-weighted (t 17.3). Among the largest fifth of
firms 3.41 bps (t 10.6). Most of it comes from the losers rising, so the long
side carries it. Present in almost every three-year window. The authors'
causes: retail buying of the day's fallers and short-sellers covering before
the close. The authors say plainly that it "might not be exploitable by many
investors after accounting for transaction costs".

**2. Same-time-of-day continuation (Heston, Korajczyk & Sadka 2010).** NYSE
stocks 2001-2005, thirteen half-hours a day. A stock's return in a given
half-hour predicts its return in the same half-hour on the following days.
Top-minus-bottom decile: about 3 bps a half-hour at a one-day lag, more than
11 bps in the opening half-hour and more than 8 near the close, still above
1 bp at five days. The authors test buying at the offer and selling at the
bid and find it **loses at every size and time of day**; they present it as a
way to time trades already planned, not as a strategy.

**3. Overnight-to-intraday reversal (Della Corte, Kosowski & Wang 2015).**
Buy at the open the stocks with the lowest overnight return, short the
highest, close at the close. Not read. It needs a trustworthy opening price
for every stock, and it trades the whole book twice a day.

**4. VWAP trend (Zarattini & Aziz 2023).** Long above the session VWAP, short
below. An index-ETF rule, close kin to the noise-area rule of research 071,
which already uses a VWAP stop and loses after Indian costs. Third-party
replications report lower figures than the authors.

**5. Reversal after block trades on the NSE (Agarwalla & Pandey).** Reported:
prices rise for 8 minutes before a block purchase, and the temporary impact
exceeds the permanent one, so part of the move reverses. The only Indian
intraday source here, and not read. Identifying blocks needs trade-level
data; minute bars hold only volume.

## What this project's own numbers say about them

Research 076 measured the cost of an intraday round trip in a large Indian
stock at about 9 bps with assumed slippage (A-056), and about 6 bps in
NIFTYBEES. A long-short rule pays that on both legs.

| Candidate | Published gross edge | Against Indian costs |
|---|---|---|
| End-of-day reversal | 3.8 to 6.9 bps a day, long-short | Below one leg's costs. Only the extreme losers could differ |
| Same-time continuation | 3 bps a half-hour; 11 at the open | Loses in its own paper. The opening half-hour is the only part near costs |
| Overnight-to-intraday reversal | not known from a primary source | Unknown; whole book turned over daily |
| VWAP trend | Sharpe 2.1 claimed on QQQ | Already tested in kind (research 071): 3 bps gross, loses |
| Block-trade reversal | not known | Cannot be built from minute bars |

The prior for every one of them is that it loses on cash stocks. The open
fade of research 076 is the reference: 8 to 9 bps gross, and it still only
broke even.

## Recommendation

Test two, in this order, as **screening runs of published settings**:

1. **End-of-day reversal**, H-0007. It is the best documented, it is the
   mirror image of the open fade that came closest in research 076, and its
   long side needs no short-selling. The Indian clock needs one decision: a
   stock with derivatives now stops trading continuously at 15:15 and is
   squared off at 15:12 (A-057), so the holding window would be 14:40 to
   15:10 and the sort would use the return to 14:10.
2. **Same-time continuation in the opening half-hour only**, H-0008. The
   paper's largest effect, and the only part of it near Indian costs.

Not recommended now: the overnight reversal (needs clean opens for every
stock; T-4004 says the panel's opens are first prints), VWAP trend (already
tested in kind), block trades (no data).

Both hypotheses are written as drafts in `hypotheses/`. Neither is coded.

**Confidence:** high that Indian evidence is scarce: the searches found
none. Moderate on the two papers' numbers: one was read in part and one
through a summary. Low on everything marked "not read".

## Open

- Read Agarwalla & Pandey from the NSE archive when it responds.
- Read SEBI's own intraday study for its cost figures; only press coverage
  was seen (70% of individual intraday traders lost money in FY 2022-23).
- The appendix of Baltussen et al. may hold international evidence; not read.
