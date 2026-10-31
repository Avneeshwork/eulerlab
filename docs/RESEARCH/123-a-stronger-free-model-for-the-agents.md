# 123 — Which free model should the research agents use, and which configured ones are dead?

**Date:** 2026-10-29 · **Confidence:** high on the dated limits and the Groq shutdown; medium on how long any free tier lasts

## Question

The operator asked for a better free model for the AI agents, one with a good
daily allowance and a paid upgrade path, and asked that useless models be
removed from `config/llm.yaml`. The assistant and the new paper agent
(ADR-084) may only use hosts whose data terms were read (ADR-064, research 073),
so a model is only a candidate if its host is already approved or its terms
were read here.

## Sources

| Source | URL | Fetched | Type |
|---|---|---|---|
| Groq, rate limits | https://console.groq.com/docs/rate-limits | 2026-10-29 | vendor docs |
| Groq, model deprecations | https://console.groq.com/docs/deprecations | 2026-10-29 | vendor docs |
| Groq, supported models | https://console.groq.com/docs/models | 2026-10-29 | vendor docs |
| OpenRouter, FAQ (free model limits) | https://openrouter.ai/docs/faq | 2026-10-29 | vendor docs |
| OpenRouter, "Free LLM API in 2026: 13 options" (updated 2026-09-24) | https://openrouter.ai/blog/tutorials/free-llm-apis-compared/ | 2026-10-29 | vendor survey, secondary for other vendors |
| Cerebras, rate limits | https://inference-docs.cerebras.ai/support/rate-limits | 2026-10-29 | vendor docs |
| Cerebras, model catalog | https://inference-docs.cerebras.ai/models/overview | 2026-10-29 | vendor docs |
| Cerebras, pricing | https://www.cerebras.ai/pricing | 2026-10-29 | vendor docs |

## Findings

1. **Groq shut down `llama-3.3-70b-versatile` on 2026-08-16.** The deprecations
   page names `openai/gpt-oss-120b` as the replacement. `config/llm.yaml` still
   pointed `groq` at the old id, so that provider has not worked for ten weeks
   (HISTORY #33). The same page retires `llama-3.1-8b-instant` (2026-08-16),
   `qwen/qwen3-32b` and Llama 4 (2026-07-17), Kimi K2 (2026-04-15) and
   `qwen/qwen3.6-27b` (2026-09-14).
2. **Groq's free limits for `openai/gpt-oss-120b`:** 30 requests a minute,
   1,000 a day, 8,000 tokens a minute, 200,000 a day. 131,072-token context,
   65,536 max completion. The page says these are base limits, that the exact
   limits are on each account's limits page, and that the Developer plan raises
   them. `qwen/qwen3.8-27b` has the same limits but is a preview model that "may
   be discontinued at short notice".
3. **OpenRouter free models:** 50 requests a day in total, or 1,000 a day once
   at least 10 credits have been bought. The FAQ says prompts are not logged by
   default. This project already restricts every OpenRouter request to
   zero-retention endpoints (ADR-064, ADR-080). The fixed
   `meta-llama/llama-3.3-70b-instruct:free` entry had no such lock and was not
   used by any code.
4. **Cerebras is no longer a free tier.** The pricing page offers a one-time $5
   credit, which needs a card and expires 30 days after activation. Its rate-limit
   page still lists a "Free Trial" (5 requests a minute, 1 million tokens a day).
   This project has no record of its data terms. Not adopted.
5. **Google AI Studio and Mistral's Experiment tier** use prompts for training,
   according to OpenRouter's survey (Google: outside the EU, UK and EEA; Mistral:
   opt-in). Both are ruled out by the no-data-leak rule (ADR-064). This was not
   checked against Google's or Mistral's own terms.

## Decision

ADR-084. New `research_agent: groq` with `openai/gpt-oss-120b`, the strongest
free model with a usable daily allowance on an approved host. If its key or ZDR
confirmation is missing, the paper agent says so and falls back to the
assistant's OpenRouter provider. Removed: `ollama-small` (3B, too weak to draft
a card), `openrouter-free` (a fixed `:free` id without the ZDR lock), `openai`
(paid, never used), and the dead Groq id. Kept: `ollama` (local, no key; the
default for the translator and the audit) and `openrouter-private` (the
assistant).

**Upgrade path, cheapest first:** buying 10 OpenRouter credits once raises its
free models from 50 to 1,000 requests a day, and nothing else changes. Groq's
Developer plan is pay-per-token with higher limits; its prices were not
fetched.

## What I could not verify

- The limits on the operator's own Groq account. The page says they can differ.
- Whether `openai/gpt-oss-120b` has a published shutdown date. None was listed on 2026-10-29.
- Groq Developer plan prices.
- Google's and Mistral's own data terms. Their exclusion rests on OpenRouter's survey.

## Open questions

- Recheck these limits on 2027-01-29 (A-019). Groq retired five model families in 2026.
