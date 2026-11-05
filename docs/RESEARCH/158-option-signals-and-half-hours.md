# 158 — Five more cash rules: option-market signals, half-hours, overnight winners

**Question.** Operator, 2026-11-05: "research 5 more and backtest", after
research 153-157 screened twenty intraday cash rules, none passing. Cash
stocks and NIFTYBEES only, 1x; options may be read as signals but not traded.

**Status.** H-0061 to H-0065 pre-registered and committed before any run.
Results follow under "Results".

## What is different this time

Every effect found so far was smaller than a round trip. This round reads
inputs not yet used: **Nifty option open interest** (where dealers' hedging
should push the index on expiry day, and how crowded puts are), and **when** in
the day a stock's return repeats.

## Sources, searched 2026-11-05

| Rule | Source | Read |
|---|---|---|
| H-0061 expiry pinning | Golez and Jackwerth (2012), "Pinning in the S&P 500 futures", *JFE* 106(3), 566-585 ([IDEAS](https://ideas.repec.org/a/eee/jfinec/v106y2012i3p566-585.html)) | Abstract and working paper record: futures finish near the closest strike more often on serial-option expiry days; delta-hedge rebalancing |
| H-0062 expiry gamma momentum | Baltussen, Da, Lammers and Martens (2021), "Hedging demand and market intraday momentum", *JFE* 142(1), 377-403 ([IDEAS](https://ideas.repec.org/a/eee/jfinec/v142y2021i1p377-403.html), [working paper](https://www3.nd.edu/~zda/intramom.pdf)) | Abstract: hedging short gamma trades with the move; intraday momentum is present when dealer gamma is negative and absent when positive |
| H-0063 put-call ratio | *Economies* 7(1) 24, 2019, Nifty put-call ratio ([PDF](https://mdpi-res.com/d_attachment/economies/economies-07-00024/article_deploy/economies-07-00024.pdf)); Pan and Poteshman (2006) | Fragments via search: PCR read as contrarian, negatively related to next-day returns, short-lived. US index evidence mostly negative ([CXO summary](https://www.cxoadvisory.com/sentiment-indicators/predictive-power-of-put-call-ratios)) |
| H-0064 same half-hour | Heston, Korajczyk and Sadka (2010), *J. Finance* ([arXiv](https://arxiv.org/abs/1005.3535)) | Already in research 078 for the opening half-hour |
| H-0065 overnight winners | Lou, Polk and Skouras (2019), *JFE* 134(1) ([LSE](https://researchonline.lse.ac.uk/id/eprint/87481)) | Abstract: overnight and intraday continuation with an offsetting cross-period reversal |

**Dropped:** an India VIX rule. Indian studies find VIX moves with the Nifty
on the day and forecasts future *volatility*; none found that it forecasts
returns ([IIM Calcutta](https://ir.iimcal.ac.in:8443/jspui/handle/123456789/3104),
[KTU](https://inzeko.ktu.lt/index.php/EE/article/view/14966)).

## The rules, fixed before running

Kite one-minute bars and the Nifty option open interest of the prior close
(`nifty_options.jsonl`), to 2024-11-29; stocks ₹1 lakh a trade, NIFTYBEES ₹10
lakh, 1x; cash-intraday charges plus 2 bps a side.

1. **H-0061 expiry pinning.** On weekly expiry day, the strike of the expiring
   series with the most call-plus-put open interest at the prior close; if the
   Nifty at 13:00 is 0.3% or more away, NIFTYBEES toward it, 13:01 to 15:10.
2. **H-0062 expiry gamma momentum.** On weekly expiry day, NIFTYBEES in the
   direction of the Nifty's move from the prior close to 14:40, 14:41 to 15:10.
3. **H-0063 put-call contrarian.** Nearest-expiry put/call open interest at
   the prior close in the top fifth of its last 250 sessions: NIFTYBEES long
   09:20 to 15:10; bottom fifth: short.
4. **H-0064 same half-hour.** Stocks ranked on yesterday's 14:40-15:10
   return; long the top decile and short the bottom, 14:40 to 15:10 today.
5. **H-0065 overnight winners.** Stocks ranked on their mean overnight move
   over 20 sessions; short the top decile and buy the bottom, 09:20 to 15:10.

Judged as before: positive net in both halves (before 2024, and 2024). No
trial spent.

## Confidence

Low. H-0061 and H-0062 have the strongest sources and the fewest days (about
150 expiries).
