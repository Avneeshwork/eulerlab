# 129 — Can the assistant use Claude, and on what data terms?

**Date:** 2026-10-29 · **Confidence:** high on retention and training terms (Anthropic's own pages); medium on prices, which change

## Question

The operator asked to "include claude all models as option" in the assistant
panel and Research Library. The assistant sends the operator's own numbers, so
a host is only allowed once its data terms are read (ADR-064). What does
Anthropic keep, does it train on API data, and what does each model cost?

## Sources

| Source | URL | Fetched | Type |
|---|---|---|---|
| Anthropic privacy centre, "How long do you store my organization's data?" (updated 2026-07-01) | https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data | 2026-10-29 | vendor policy |
| Anthropic docs, "API and data retention" | https://platform.claude.com/docs/en/manage-claude/api-and-data-retention | 2026-10-29 | vendor docs |
| Anthropic's model and price table, as bundled with Claude Code's `claude-api` reference (cached 2026-10-06) | https://platform.claude.com/docs/en/about-claude/pricing | 2026-10-29 | vendor docs, via the bundled copy; the live page was not fetched |

## Findings

1. **Retention.** Anthropic deletes API inputs and outputs "within 30 days of
   receipt or generation", with exceptions for features you choose that store
   data, agreements, usage-policy enforcement and the law (privacy centre).
   The docs page says conversation content is not retained by default, except
   for Covered Models, which require 30-day retention. The two pages differ in
   wording; this project takes the stricter reading: up to 30 days.
2. **Training.** "Retained data is never used for model training without your
   express permission" (docs page).
3. **Zero retention is not self-serve.** It is enabled per organisation by
   Anthropic's sales team. There is no account switch like Groq's.
4. **Covered Models.** Claude Fable 5.1 (and Fable 5, Mythos 5 and 5.1) always
   require 30-day retention; a ZDR organisation must enable it per workspace.
5. **Prices** per million tokens, input / output: Opus 5.5 $4 / $20; Sonnet 5.5
   $2 / $10; Haiku 5.5 $0.10 / $0.50 (up to 100k-token prompts); Fable 5.1
   $10 / $50. None is free.
6. **API shape.** Claude's Messages API is not the OpenAI chat shape the
   assistant uses. Anthropic's guidance is to use its official SDK. The current
   models reject `temperature` (from 2026-10-21, every model), keep thinking on,
   and require thinking blocks to be passed back unchanged in a tool loop.
   Safety classifiers can decline with `stop_reason: "refusal"`; a server-side
   fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`)
   re-runs the request on a recommended model. Haiku 5.5 has no fallback.

## Not found

- The live pricing page was not fetched; prices come from the bundled copy.
- No statement on where (which country) API requests are processed by default.

## Decision

Add `api.anthropic.com` to the approved hosts with its own policy label
("kept up to 30 days, not used for training"), not the zero-retention lock.
The operator accepted these terms on 2026-10-29. All four current models are
listed, marked paid, and never used as a silent fallback. ADR-095.

## Open questions

- If the operator later wants zero retention, it needs a sales agreement and
  rules out Fable 5.1 outside a 30-day workspace.
