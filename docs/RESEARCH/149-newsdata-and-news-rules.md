# 149 — Is NewsData.io better than what we have, and how can sentiment be corrected with no AI tokens?

## Question

The operator, 2026-11-04: the oil story is one case; sentiment can be wrong in many, and with no AI tokens nothing corrects it. Should a knowledge base catch wrong cases and grow over time? They added a NewsData.io key ("use that if better") and asked for sentiment on each stock where possible.

## Sources

- A. NewsData.io `/api/1/latest` with the operator's key (`News_Data_io`), measured 2026-11-04. Fields include `sentiment`, `sentiment_stats` (positive, neutral, negative in %), `ai_tag`, `ai_region`; `ai_org` answered "ONLY AVAILABLE IN CORPORATE PLANS". `country=in&category=business` returned US Form 4 filings and a Hyderabad lottery story. `q=Nifty`: India stories, sentiment mostly sensible ("Eight of India's top 10 firms lose Rs 1.55 lakh crore" 97.7% negative). `q=Reliance Industries`: an ultrasound market report, a Nigerian military story. "India's Nifty 50 Reaches Two-Month High as Oil and Options Raise Caution": 97.9% positive. Some results carry no sentiment.
- B. NewsData.io pricing (research 148, C): 200 credits a day, 48 hours of history.
- C. Research 148 (K): the local tone model on 39 headlines.
- D. Measured: the full brief run with rules, 2026-11-04. Of 12 judged stories, the rules matched 6 and agreed with the judgement on 5; the sixth was a market recap judged "none".

## Findings

- NewsData's sentiment, like the local model's, scores words, not economics (A). Its search is noisier than Currents' for company names (A). It is a second source and a second opinion, not a replacement.
- The disagreements in research 148 are few kinds that recur: crude, rates, the rupee, foreign flows, conflict, tariffs, inflation (C). A short list of written rules covers them and needs no model (D).
- A judged story is evidence for or against a rule; logging every judgement lets rules be added and removed by counting, with the whole log giving the same rules each time.

## Decision

ADR-135: written seed rules in `config/news_rules.yaml`; learned rules rebuilt from the judgement log (on at 3 agreeing, off at 2 against, A-105); NewsData kept beside our score with agreement against the judged direction reported; per-stock tone from the per-instrument headlines.

## Confidence

Medium. The rule list is written from one day's disagreements; the learned rules start empty and need weeks of judgements.

## Open questions

- Agreement with the model's judgement is not agreement with the market. Score both scores and rules against the next session's move once enough are logged (T-4433).
- Learned rules use fixed subject and movement word groups; a new kind of story outside them cannot be learned until a group is added.
