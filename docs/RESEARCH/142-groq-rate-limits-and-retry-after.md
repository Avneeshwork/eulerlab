# 142 — What does Groq send when a request hits its rate limit, and what are gpt-oss-120b's limits?

## Question

On 2026-11-03 a live test of the knowledge agent on Groq failed with HTTP 429 after four requests in two seconds. Does Groq say how long to wait, so the client can wait once instead of failing the task?

## Sources

- A. Groq, "Rate Limits", https://console.groq.com/docs/rate-limits, fetched 2026-11-03.

## Findings

- Groq answers an exceeded limit with HTTP 429 (A).
- `retry-after` is "only set if you hit the rate limit and status code 429 is returned", in seconds; the page's example is 2 (A).
- For `openai/gpt-oss-120b` the page lists 30 requests a minute, 1,000 a day, 8,000 tokens a minute and 200,000 a day (A). The page says the table shows "the base limits for the Developer plan", so it does not clearly state the free tier's values; research 123 recorded the same figures as the free limits.

## Decision

`assistant/chat._post` waits out a 429's `retry-after` once when it is 20 seconds or less, then retries; otherwise it fails as before (`ModelUnavailable`). The doctor now treats a failed run whose summary starts `ModelUnavailable`, `Refused` or `BudgetSpent` as `model_down`, not as a code error for the engineering agent (HISTORY #64).

## Confidence

High that a short `retry-after` is sent (primary source). Medium on the free tier's exact limits.

## Not found

The free tier's own limits for this model, stated as such. Whether `retry-after` is ever fractional.

## Open questions

Whether the knowledge agent's tool loop fits in 8,000 tokens a minute for long questions (T-4402).
