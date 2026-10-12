# 073 — A free assistant that does not leak the operator's data

**Question.** Operator, 2026-10-11: "setup a free ai assistance which help me
evaluate data, ask questions related to my strategies, research, trades ... but
ensure no data leak to ai, should have floating icon over screen". Where can
the model run, for free, without the operator's data being kept or trained on?

## This machine, measured 2026-10-11

Apple M1, 8 GB of memory, 1.4 GB free of 228 GB. No Ollama, LM Studio or
llama.cpp installed. A local model small enough for 8 GB is about 2 GB on
disk, so it does not fit. The operator then asked for a cloud plan.

## Sources, fetched 2026-10-12

| Source | URL | What it says |
|---|---|---|
| Oracle, Always Free Resources | https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm | "the first 1,500 OCPU hours and 9,000 GB hours per month ... For Always Free tenancies, this is equivalent to 2 OCPUs and 12 GB of memory." 200 GB block storage. "Idle Always Free compute instances may be reclaimed" (7 days under 20% CPU, network and memory) |
| Google, Gemini API Additional Terms | https://ai.google.dev/gemini-api/terms | Unpaid Services: Google uses submitted content and responses to "develop Google products and services and machine learning technologies"; "human reviewers may read, annotate, and process your API input and output"; "Do not submit sensitive, confidential, or personal information to the Unpaid Services." |
| Groq, Your Data | https://console.groq.com/docs/your-data | "By default, Groq does not retain customer data for inference requests." Inputs and outputs may be logged for reliability or abuse cases, "retained for up to 30 days". "All customers may enable Zero Data Retention (ZDR)" in Data Controls, which stops that too |
| Groq, Models | https://console.groq.com/docs/models | Production: `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, each with a 131,072-token context |
| Groq, Tool Use | https://console.groq.com/docs/tool-use | "all models hosted on Groq support tool use". Tools go in a `tools` array; the reply carries `tool_calls`; results return as `role: "tool"` with `tool_call_id` |
| Groq, Rate Limits | https://console.groq.com/docs/rate-limits | Developer-plan base limits only (30 requests a minute, 1,000 a day, 8,000 tokens a minute for the gpt-oss models) |
| Cloudflare, Workers AI pricing | https://developers.cloudflare.com/workers-ai/platform/pricing/ | "10,000 Neurons per day at no charge", on the Workers Free plan |
| InfoQ and others (search, 2026-10-11) | https://infoq.com/news/2026/07/oracle-cloud-free-tier-limits/ | Oracle's free Arm allowance was halved in 2026 from 4 OCPU and 24 GB. Secondary; the Oracle page above confirms the new figure |

## Findings

1. **Gemini's free tier is ruled out.** Its own terms say prompts train models,
   people may read them, and confidential data should not be sent.
2. **A server of the operator's own (Oracle) leaks to no AI company**, but it is
   two CPU cores with no GPU. Speed was not measured; expect it to be slow.
3. **Groq keeps nothing by default and offers Zero Data Retention to every
   customer.** The data still passes through Groq's servers.

## What could not be found

- Groq's **free-plan** rate limits. The page shows only the Developer plan and
  says the exact figures are on the account's own limits page.
- Whether Groq **trains** on inputs. The page speaks of retention, not
  training. Data that is not retained cannot be trained on later, but that is
  an inference, not their statement.
- Whether **streaming** works together with tool calls on Groq. Not used.
- Cloudflare's data terms for Workers AI. The search quota ran out; not used.
- Any way for code to **check** that Zero Data Retention is on in an account.

## Decision

Groq, with Zero Data Retention on. The operator chose it on 2026-10-12 over
their own Oracle server, after seeing both. ADR-064.

## Confidence

High on the quoted terms (primary pages, read the day of the decision). Terms
change: recheck date in A-054. Low on quota, which is unmeasured.
