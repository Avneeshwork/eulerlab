# 157 — Five more cash rules: intraday persistence, volume and attention

**Question.** Operator, 2026-11-05: "research on 5 more strategies", after
research 153-156 screened fifteen intraday cash rules and a filter search, none
passing. Cash stocks and NIFTYBEES, 1x, minute bars, no derivatives.

**Status.** H-0056 to H-0060 pre-registered and committed before any run.
Results follow under "Results".

## What is different this time

Research 155-156 traded price events (breakouts, bursts, panics) and calendar
days. Prices after a large intraday move here tend to **continue**, not reverse
(H-0047, H-0048, H-0051), and a break of the 52-week high **falls back** on the
day (H-0046). This round uses three other inputs the earlier rules ignored:

- a stock's own **history of daytime returns** (H-0056);
- **volume** as distinct from price: a volume shock without a price move
  (H-0057), and yesterday's big move split by its volume (H-0059, H-0060);
- **attention**: the first time a stock is up 5% on the day (H-0058).

## Sources, searched 2026-11-05

| Rule | Source | Read |
|---|---|---|
| H-0056 | Lou, Polk and Skouras (2019), "A tug of war: overnight versus intraday expected returns", *JFE* 134(1), 192-213 ([LSE](https://researchonline.lse.ac.uk/id/eprint/87481), [PDF](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf)) | Abstract and summaries: firm-level intraday returns continue for years; past-month intraday winners keep earning intraday and earn less overnight |
| H-0057 | Gervais, Kaniel and Mingelgrin (2001), "The high-volume return premium", *J. Finance* 56(3), 877-919 ([IDEAS](https://ideas.repec.org/a/bla/jfinan/v56y2001i3p877-919.html)) | Abstract: unusually high volume over a day or week is followed by gains over the next month (visibility); stronger when the volume is not accompanied by an extreme return |
| H-0058 | Seasholes and Wu (2007), "Predictable behavior, profits, and attention", *J. Empirical Finance* 14(5), 590-610 ([RePEc](https://econpapers.repec.org/RePEc:eee:empfin:v:14:y:2007:i:5:p:590-610), [PDF](https://www.bauer.uh.edu/wu/Papers/JEF2007_Attention.pdf)) | Abstract and a summary of the working paper: Shanghai upper-limit hits draw individual buyers; traders who buy during the event earn about 0.76% the next day after costs (working-paper figure, not checked against the published version) |
| H-0059, H-0060 | Parthasarathy (2019), *Review of Behavioral Finance* ([RePEc](https://econpapers.repec.org/RePEc:eme:rbfpps:rbf-06-2018-0058)) | Abstract via search: on Indian stocks, large one-day price changes on low volume reverse and on high volume continue over the next 20 days |

**Dropped:** a day-of-week rule for NIFTYBEES (Indian studies disagree on the
sign: a 2014 study finds Friday highest and Monday lowest but insignificant,
an MPRA paper finds positive Monday effects); the MAX lottery effect (Bali,
Cakici and Whitelaw 2011), whose Indian evidence is split and which overlaps
H-0059.

## The rules, fixed before running

Kite one-minute bars to 2024-11-29; stocks ₹1 lakh a trade and NIFTYBEES ₹10
lakh, 1x; cash-intraday charges plus 2 bps a side. Exact settings are in each
hypothesis file.

1. **H-0056 intraday persistence.** Each morning, rank stocks by their mean
   09:20-15:10 return over the previous 20 sessions; long the top decile, short
   the bottom, 09:20 to 15:10.
2. **H-0057 quiet volume shock.** At 10:15, first-hour volume at least 3× its
   14-session norm and a move under 0.5% from the prior close: buy the ten with
   the highest ratio at 10:16, sell at 15:10.
3. **H-0058 attention at +5%.** The first minute from 09:30 a stock closes 5%
   or more above the prior close (not a day that opened there): buy the next
   open, sell at 15:10.
4. **H-0059 big day, split by volume.** Yesterday's close-to-close move of 4%
   or more: fade it if yesterday's volume was below the 14-session mean,
   follow it if at least twice the mean; 09:20 to 15:10.
5. **H-0060 the same for the Nifty.** A 1.5% Nifty day: NIFTYBEES against it if
   NIFTYBEES volume was below its 14-session mean, with it otherwise.

Judged as before: positive net in both halves (before 2024, and 2024). No
trial spent.

## Confidence

Low. H-0059 is the only rule with Indian evidence behind it.

## Results (run 2026-11-05, after the rules were committed in `710964a`)

`make cash-volume` → `data/derived/cash_volume.json`. 416 stocks; 1x; no trial
spent.

| Rule | Trades | Gross a trade | Net a trade | Net Sharpe | Before 2024 / 2024 (net Sharpe) |
|---|---|---|---|---|---|
| H-0056 intraday persistence (deciles) | 46,985 | 5.22 bps | -7.04 bps | -2.83 | -3.44 / -1.64 |
| H-0057 quiet volume shock | 1,226 | -7.71 bps | -19.98 bps | -1.87 | -1.87 / -1.86 |
| H-0058 attention at +5% | 6,809 | 7.83 bps | -4.44 bps | -0.53 | -0.27 / -1.14 |
| H-0059 big day split by volume | 7,362 | -3.78 bps | -16.04 bps | -1.90 | -1.42 / -2.81 |
| H-0060 big Nifty day split, NIFTYBEES | 64 | -5.09 bps | -13.09 bps | -0.70 | -0.44 / -1.30 |

**All five are dead**, negative net in both halves.

- **Intraday persistence is real but small:** a stock's past daytime winners
  did beat its losers the next day, by 5.2 bps a position, against a 12.24 bps
  round trip. Lou, Polk and Skouras's effect exists here at about the size of
  every other intraday effect found today.
- **Attention at +5%** made 7.8 bps gross, also below the cost.
- **A heavy, quiet first hour** was followed by a fall (-7.7 bps), not the
  visibility premium; that premium is measured over a month.
- **Yesterday's big day, split by volume**, lost before costs; Parthasarathy's
  20-day pattern is not visible in the next session.

Across research 153-157, twenty intraday cash rules and one filter search were
screened on 2026-11-05. The largest gross edge of any stock rule was 9.5 bps a
trade (the in-play filter on its selection window); a ₹1 lakh round trip costs
12.24.
