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

(Added after the runs.)
