# 171 — Ten stock day trades at 1x: news and no-news moves, and relatives of the survivors

**Question.** Operator, 2026-11-07: "keep researching mor strategies take 1x
capital now". NSE cash stocks, intraday, no leverage.

**Status.** H-0141 to H-0150 pre-registered and committed before any run.
Results follow under "Results".

## Set-up

₹1 lakh a position at 1x, at most ten open on ₹10 lakh of capital: 12.24 bps
a round trip (research 154). That is 3.8 bps more than research 168-170's
₹5 lakh positions, so a rule needs about 12 bps gross a trade. Of the earlier
survivors only H-0132 (17.4) and H-0118 (17.2) had that much. Same snapshots,
fills, liquidity ranking and window as research 168 (2021-11-01 to
2024-10-15). Screen as research 170: gated only if net positive in both
halves and at twice the costs.

## News and no news

Chan (2003, *JFE* 70(2), 223-260, "Stock price reaction to news and no-news:
drift and reversal after headlines", cited from memory, not fetched): large
monthly moves without a headline reverse, moves with one drift. H-0141 to
H-0144 test that at the open and the next day, with news = an NSE filing in
`nse_announcements` that is not administrative. Fixed before any run, these
categories are **not** news: Loss of Share Certificates (both spellings),
Issue of Duplicate Share Certificate, Trading Window, Closure of trading
window, Copy of Newspaper Publication, Newspaper Advertisements, Certificate
under SEBI (Depositories and Participants) Regulations 2018, Shareholders
meeting, Annual General Meeting, Postal Ballot, Book Closure, Record Date,
Registrar & Share Transfer Agent Update, Code of Conduct under SEBI(PIT) Reg.
2015, ESOP/ESOS/ESPS, ESOP/ESPS/SBEB Scheme, Allotment of Securities, Change in
Company Secretary/Compliance Officer, Annual Secretarial Compliance Report,
Monitoring Agency Report, Analysts/Institutional Investor Meet/Con. Call
Updates, Schedule of Analysts/Institutional Investor Meet/Con. Call,
Transcript of Analysts/Institutional Investor Meet/Con. Call, Recording of
Analysts/Institutional Investor Meet/Con. Call.

## The rules

| Card | Idea | Source |
|---|---|---|
| H-0141 | Fade a 2% gap with no filing | Chan (2003) |
| H-0142 | Follow a 2% gap with a filing | Chan (2003) |
| H-0143 | Fade yesterday's 4% move with no filing | Chan (2003) |
| H-0144 | Follow yesterday's 4% move with a filing | Chan (2003) |
| H-0145 | Tug of war, three a side, 1x | H-0132's relative |
| H-0146 | Tug of war where today's gap agrees | H-0132 and H-0131 |
| H-0147 | Short on every ban day after the first | H-0096's relative |
| H-0148 | High-beta stocks before a holiday | Ariel (1990); H-0052 |
| H-0149 | Monday fade of Friday's movers | Chen and Singal (2003) |
| H-0150 | Strong close on heavy turnover, next day | practitioner |

H-0145 to H-0147 are relatives of rules that passed and are flagged as such:
a pass among them is weaker evidence than one among the other seven.

## Results

Screen 2026-11-07 (`make onex-screen`), no trial spent; then the gate for
the one rule that passed. Bps a trade at ₹1 lakh, 1x; cost 12.25-12.27.

| Card | Trades a day | Gross | Net | Net Sharpe | Halves | At 2x costs | Verdict |
|---|---|---|---|---|---|---|---|
| H-0141 | 7.89 | 17.52 | 5.26 | 0.468 | -0.012 / 0.904 | -0.629 | screen fail |
| H-0142 | 3.46 | 4.66 | -7.59 | -0.564 | 0.448 / -1.347 | -1.493 | screen fail |
| H-0143 | 8.08 | 6.93 | -5.33 | -0.43 | -1.239 / 0.223 | -1.428 | screen fail |
| H-0144 | 3.64 | -0.13 | -12.39 | -0.786 | 0.143 / -1.502 | -1.558 | screen fail |
| H-0145 | 6.0 | 22.75 | 10.49 | 1.435 | 2.639 / 0.186 | -0.243 | screen fail |
| H-0146 | 6.6 | 27.53 | 15.26 | 1.567 | 2.374 / 0.625 | 0.311 | **PROMOTE** |
| H-0147 | 2.71 | -1.46 | -13.71 | -1.003 | -0.188 / -1.45 | -1.889 | screen fail |
| H-0148 | 0.55 | 30.64 | 18.38 | 0.392 | 1.255 / -0.553 | 0.131 | screen fail |
| H-0149 | 2.13 | 10.81 | -1.46 | -0.112 | 0.07 / -0.322 | -1.097 | screen fail |
| H-0150 | 1.57 | -6.67 | -18.93 | -0.849 | -0.525 / -1.08 | -1.396 | screen fail |

1. **H-0146 PROMOTE (ledger #112, #113)**: the tug of war only where today's
   gap agrees. 27.5 bps gross a trade, the largest of any stock rule here
   with more than a trade a day. 2022 +52%, 2023 +41%, 2024 to October -4%;
   drawdown -14%. It is H-0132 made stricter after H-0132 passed, so it adds
   confidence in the effect only through its larger per-trade edge, not as a
   second discovery. Strict bar: fails (deflated Sharpe 0.768, Romano-Wolf).
2. **Chan's news/no-news split shows, but not enough to trade.** Fading no-news
   gaps made 17.5 bps gross, following news gaps 4.7; fading no-news moves next
   day 6.9, following news moves -0.1. The no-news gap fade had a flat first
   half (Sharpe -0.01).
3. Shorting every ban day after the first loses (-1.5 bps gross): the ban
   effect is the first day (H-0096), not the ban.
4. High-beta stocks before holidays made 30.6 bps gross on 400 trades but lost
   in the second half.
