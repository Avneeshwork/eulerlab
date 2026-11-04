# 147 — What can the brief honestly forecast about the next Nifty session, and how is it checked?

## Question

The operator asked on 2026-11-04 for the brief to forecast the next session's behaviour from the data held, explain it in detail, test each day's forecast against what happened and keep updating the model. What does the literature say is forecastable a day ahead, from daily data, and how should a forecast be scored?

## Sources

- A. Corsi, F. (2009), "A Simple Approximate Long-Memory Model of Realized Volatility", *Journal of Financial Econometrics* 7(2), 174–196. Record and abstract at https://econpapers.repec.org/RePEc:oup:jfinec:v:7:y:2009:i:2:p:174-196, fetched 2026-11-04. SSRN (https://papers.ssrn.com/abstract=1365738) answered 403; the full text was not read.
- B. Chou, R. Y. (2005), "Forecasting Financial Volatilities with Extreme Values: The Conditional Autoregressive Range (CARR) Model", *Journal of Money, Credit and Banking* 37(3), 561–582. Record and abstract at https://ideas.repec.org/a/mcb/jmoncb/v37y2005i3p561-82.html, fetched 2026-11-04. Full text not read.
- C. NSE research paper 39 on NASDAQ and Nifty daytime and overnight returns, https://nsearchives.nseindia.com/content/research/Paper39.pdf. The fetch timed out on 2026-11-04; what is below comes from the search result's summary only, not the paper.
- D. "Volatility Spillovers" in the *IUP Journal of Financial Economics*, https://iupindia.in/1207/IJFE_VolatilitySpillovers7.pdf. Fetched 2026-11-04 but the PDF's text could not be extracted; only the search summary was read.
- E. Gneiting, T. and Raftery, A. E. (2007), "Strictly Proper Scoring Rules, Prediction, and Estimation", *JASA* 102(477), 359–378. Search result only (https://apps.dtic.mil/sti/pdfs/ADA459827.pdf is the 2004 technical report); not fetched.
- F. This project: research 072 and T-4042 (Mukherjee & Mandal 2025 on Nifty gaps), `data/derived/gap_forecast.json`.
- G. Measured: `forecast/next_session.check` on Nifty 50 daily bars 2015-01-01 to 2026-11-03, walk-forward over the last 500 sessions, 2026-11-04.

## Findings

- Volatility is forecastable a day ahead; direction mostly is not. A cascade of yesterday's, last week's and last month's volatility forecasts realised volatility well out of sample (A). The high-low range is an efficient measure of volatility and modelling its dynamics beats GARCH out of sample on the S&P 500 (B).
- The US session moves India's next open: past daytime returns of NASDAQ and Nifty both bear on Nifty's overnight return, and NASDAQ's daytime volatility shocks explain far more of Nifty's overnight volatility than Nifty's own (C, D; summaries only, 1999–2001 data and older).
- In this project, a published gap-direction model was beaten by always saying "up": Nifty opens higher on 68.7% of days, and signals lifted 2–5 points over that base rate (F).
- Probability forecasts should be scored with a proper scoring rule, so that the honest probability scores best; the Brier score is one (E). An interval is judged on coverage and width (E).
- Measured (G): the range model's average log error was 0.32 against VIX-implied range's 0.52; the 80% close band held the close on 78% of days; the higher-open odds scored Brier 0.2488 against the base rate's 0.2562 (skill +2.9%); the higher-close odds 0.2528 against 0.2530 (skill +0.1%), direction right 48% of days.

## Decision

ADR-133: the forecast leads with the range and the close band, gives direction as odds next to the base rate, and says when the odds are no better than a coin flip. Each forecast is logged before its session and scored after it; the base rate replaces the model's odds whenever the model trails it. These are not strategy papers: no `hypotheses/` spec is written, and nothing trades on the forecast.

## Confidence

High for the range (A, B and G agree). Low for direction: the measured skill is small (G) and the US-spillover papers (C, D) were not read in full and are old.

## Open questions

- C and D in full: the fetch timed out and the PDF was unreadable. Retry, or find a recent study of the S&P 500 and GIFT Nifty against the Nifty open.
- GIFT Nifty's pre-open price would be a far better gap input than the prior US session; no free source with history is held.
- The second stage (FII cash, US session) rests on about 270 sessions of FII data; its weight should be re-read once a year of live scores exists.
