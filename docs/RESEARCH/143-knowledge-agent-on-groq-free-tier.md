# 143 — Why did the knowledge agent overrun Groq's free tier, and what makes it fit?

## Question

On 2026-11-03 the knowledge agent failed live on Groq twice (T-4402): HTTP 429 after four requests in two seconds, then HTTP 400. The operator asked why it sends so many requests so fast, and to cut its usage.

## Sources

- A. Groq, "Rate Limits", https://console.groq.com/docs/rate-limits, fetched 2026-11-03.
- B. Groq, "Tool Use", https://console.groq.com/docs/tool-use, fetched 2026-11-03.
- C. Groq, "Error Codes", https://console.groq.com/docs/errors, fetched 2026-11-03.
- D. Measured: three requests to `openai/gpt-oss-120b` on 2026-11-03, reading the `x-ratelimit-*` headers; then live knowledge questions with each request's size and Groq's `usage` logged.

## Findings

- gpt-oss-120b has no parallel tool use (B's table). So every lookup is its own request, and each request re-sends the whole thread: instructions, every tool description and every result so far. A question's cost grows with the square of its lookups.
- Before: all 17 tools were offered, 5,878 characters of descriptions (about 1,500 tokens) in every request; up to 6 rounds, plus 6 more if the figure check sent the answer back. Rounds went back to back. Estimated one question: about 18,000 tokens in under a minute. The limit is 8,000 tokens a minute (A; Groq's own `x-ratelimit-limit-tokens` header said 8000, D).
- A and C do not say whether `max_tokens` counts toward the minute's limit. Measured (D): remaining tokens fell by about 330 per small request whether `max_tokens` was 4,096 or 256. So only tokens used count; lowering `max_tokens` would save nothing.
- The allowance refills continuously: after 332 tokens, `x-ratelimit-reset-tokens` said 2.49 s, which is 8,000 a minute spread evenly (D).
- The 400 in the second failure was "Tool choice is none, but model called a tool" (`tool_use_failed`): on the last round, which offers no tools, gpt-oss-120b still wrote a tool call (once an invented `repo_browser.open_file`, once `read_document`). An extra instruction not to call a tool did not stop it. It stopped when the last round got the tool results as one plain message, with no tool calls in the thread (D). Its retry failed identically both times.
- C says nothing about `output_parse_failed`, `tool_use_failed` or what to do about them.

## Decision

ADR-125. Pace every request to the provider's `tokens_per_minute` (Groq: 8,000), refilling continuously and correcting from Groq's `x-ratelimit-remaining-tokens`; offer the knowledge agent its 10 tools, not 17; cap it at 4 rounds plus 2 for the retry; give the last round the results as plain text; send an `output_parse_failed` request once more.

After (D), two live questions: 4 requests each, 8,869 and 8,901 tokens, 42–44 seconds, no 429, every figure checked and supported (3 and 12 figures). The second question had failed every time before.

## Confidence

High on the cause (measured request by request). Medium that four rounds are enough: both live questions used three lookups and then answered; a question needing more gets "not held" for what it could not read.

## Not found

Whether a 400 counts against the daily request or token allowance. Whether `output_parse_failed` usually clears on a second try (A-096).

## Open questions

The daily limit, 200,000 tokens (A), allows about 22 such questions a day if nothing else uses Groq.
