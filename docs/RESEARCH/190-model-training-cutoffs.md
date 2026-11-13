# 190 — What a language model remembers of the market, and each model's training cutoff

**Date:** 2026-11-13. **For:** ADR-176, issue #141.

## Question

Which sessions may a model-judged signal (news impact, a forecast) be backtested on, for the models EulerLab uses?

## Sources

| Source | URL | Fetched |
|---|---|---|
| Anthropic, Models overview (table rows "Training data cutoff" and "Reliable knowledge cutoff") | https://platform.claude.com/docs/en/about-claude/models/overview.md | 2026-11-13 |
| Lopez-Lira, Tang and Zhu (2025), "The Memorization Problem: Can We Trust LLMs' Economic Forecasts?" | cited from the roadmap document's research, not re-fetched today | 2026-11-12 |
| Gao, Jiang and Yan (2026), on look-ahead in LLM return forecasts | cited from the roadmap document's research, not re-fetched today | 2026-11-12 |

## Findings

- Anthropic's table gives **Jun 2026** as both the training data cutoff and the reliable knowledge cutoff for Claude Fable 5.2, Opus 5.5, Sonnet 5.5 and Haiku 5.5. The page gives a month, not a day.
- The two papers report that models recall pre-cutoff index levels and returns closely, and that an instruction to ignore later data does not remove the effect. Only data after the cutoff is a fair test.

## Decision

`config/model_cutoffs.yaml` holds 2026-06-30 for the four Claude models (the last day of the month given). A model-judged signal is refused on any window starting on or before the cutoff. A model with no entry cannot be backtested at all.

## Confidence

High for the four Claude dates (primary source, fetched today). The rule itself is conservative by design.

## What was not found

- No cutoff was sourced for Groq's `openai/gpt-oss-120b`, for Claude Fable 5.1 (`claude-fable` in `config/llm.yaml` still points at it), for the OpenRouter model, or for the local `qwen2.5-coder`. They are left out of the file, so their judgements cannot be backtested. Groq is the model that judges news impact today, so `news_impact` is forward-only until a cutoff is sourced or the judge is changed (T-4588).
- The tone scorer (`distilroberta-finetuned-financial-news-sentiment`) is a classifier, not a generative model. It is not covered by this rule. Whether its training data overlaps the backtest years was not checked.
- The probe has not been run against any real model (T-4588).

## Recheck

A new model version has a new cutoff. Recheck when `config/llm.yaml` changes, and by 2027-02-13.
