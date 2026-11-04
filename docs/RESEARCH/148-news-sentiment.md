# 148 — Which free source gives the brief market-wide news with sentiment, and is FinBERT good enough on its own?

## Question

The operator, 2026-11-04: crashes are hard to predict and the brief takes no news, so it misses geopolitical and country-wide news; show news sentiment and its possible impact. Then: "check for free platform which can show sentiment for all news type we need", "is CURRENT_NEWS_API not useful", and "look over open source FinBert github repo… it will get better as it is made for that".

## Sources

- A. GDELT, https://www.gdeltproject.org/, fetched 2026-11-04: "100% free and open", monitors nearly every country in over 100 languages, updates every 15 minutes, archives from 1979.
- B. GDELT DOC 2.0 API, `api.gdeltproject.org/api/v2/doc/doc`, measured 2026-11-04: a `timelinetone` query for "sensex" returned daily average tone; an `artlist` query returned India stories ("Iran US War News", US midterms, a Supreme Court ruling); a two-year tone query answered "Please limit requests to one every 5 seconds" even when it was the first request.
- C. NewsData.io pricing, https://newsdata.io/pricing, fetched 2026-11-04: free plan 200 credits a day, "AI tags & sentiment analysis" included, history 48 hours, "for testing & personal projects".
- D. Marketaux pricing and docs, https://www.marketaux.com/pricing and /documentation, fetched 2026-11-04: free 100 requests a day × 3 articles; sentiment −1 to +1 per company entity; `countries=in` filter; built around entities.
- E. Alpha Vantage documentation, https://www.alphavantage.co/documentation/, fetched 2026-11-04: `NEWS_SENTIMENT` is labelled premium.
- F. Finnhub pricing and news-sentiment docs: the pages did not render on 2026-11-04; nothing confirmed.
- G. Currents API docs and pricing, https://currentsapi.services/en/docs/ and /en/pricing, fetched 2026-11-04: free 250 requests a day, 20 results each, 30 days back, at most 7 days per search, commercial use with attribution; no sentiment field. Measured with the operator's key: India "Nifty" search returned GIFT Nifty, Asia, Brent and US-midterm stories; fields `title, description, category, author, url, published`; a range of exactly 7 days answers 400 "Max range is 7 days", and a start 30 days back answers 400 "Max lookback is 30 days".
- H. ProsusAI/finBERT, https://github.com/ProsusAI/finBERT, fetched 2026-11-04: code Apache-2.0, which "does not cover" the model weights or Financial PhraseBank. ProsusAI/finbert model card, https://huggingface.co/ProsusAI/finbert: weights CC BY-NC-SA 4.0, "non-commercial purposes only".
- I. mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis, https://huggingface.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis, fetched 2026-11-04: Apache-2.0, 82.1M parameters, Financial PhraseBank, 0.982 accuracy (self-reported). Revision `ae0eab9ad336d7d548e0efe394b07c04bcaf6e91` from the Hugging Face API.
- J. yiyanghkust/finbert-tone model card: analyst-report training data; licence not stated.
- K. Measured: ProsusAI/finbert and model I on 39 de-duplicated India headlines from Currents, 2026-11-04, on CPU.

## Findings

- No free platform gives sentiment for every kind of news we need. GDELT has tone and long history but is throttled (A, B); NewsData.io has sentiment but 48 hours of history (C); Marketaux scores companies, not macro or geopolitics (D); Alpha Vantage's sentiment is paid (E); Currents has good India coverage and no sentiment (G).
- Both FinBERT-style models load in about 40 s and score 39 headlines in 1.4–2.0 s on CPU (K).
- On market-move headlines both are right ("GIFT Nifty signals negative open" −0.95 and −1.00; "Sensex gains over 300 points" +0.88 and +1.00) (K).
- They score words, not economics: "Crude oil falls below $104" −0.88 and −1.00 although cheaper oil helps India; "Rising crude could push India's inflation up 1 point" +0.91 and +1.00; FinBERT read "SBI chair backs a 50 bp rate hike" +0.74, model I −0.99; "nuclear fears… age of panic?" came out neutral for both; an OTP-fraud payout story scored +0.49 and +1.00 (K).
- In the full brief run, choosing stories to judge by strongest tone picked market recaps ("Sensex rises over 1,000 points" judged high severity) and no geopolitical story; drawing from each theme in turn with recaps removed brought in US–Iran tensions, the midterms and SEBI's tax proposal (measured 2026-11-04).

## Decision

ADR-134: Currents for headlines and summaries (Google News as fallback); model I, run locally and pinned, for the tone of every relevant story; one model request per brief to judge the impact of up to 12 stories drawn from each theme in turn, each line checked against its story; news shown beside the forecast, not in it, until tested (T-4433). FinBERT's own weights were not used (H).

## Confidence

Medium. The tone test is 39 headlines on one day; the impact judgement is a model's and is only checked for form and figures, not for being right.

## Open questions

- Does news tone forecast the next session's range or direction? Needs history known at the time: GDELT's tone timeline (B), fetched politely, or 60 sessions of our own log.
- NewsData.io's free sentiment (C) could be a second, independent score for the last 48 hours if the operator adds a key.
