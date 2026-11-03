# 146 — How does the research agent search CORE and Semantic Scholar with the operator's free keys?

## Question

The operator added free keys for OpenAlex, CORE and Semantic Scholar (T-4413, 2026-11-03): "ALL API ADDED". How is each key sent, what are the limits, and do the results suit the research agent?

## Sources

- A. CORE API v3 documentation, https://api.core.ac.uk/docs/v3, fetched 2026-11-03 (rate limits table, "how to call the API", PDF download policy).
- B. Semantic Scholar API product page, https://www.semanticscholar.org/product/api, fetched 2026-11-03. Its API docs page, https://api.semanticscholar.org/api-docs/, answered HTTP 429 and was not read.
- C. Measured: calls to `api.core.ac.uk/v3/search/works`, `api.semanticscholar.org/graph/v1/paper/search` (and `/search/bulk`, `/paper/DOI:...`), and `api.openalex.org/works` with each key, 2026-11-03. Key values were never printed.
- D. Measured: `paper_search.search` on two topics with all six sources, 2026-11-03.

## Findings

- CORE: key as `Authorization: Bearer <key>`, or `api_key=` in the URL (A). Registered personal users get 1,000 tokens a day, at most 25 a minute (A); the response header said `x-ratelimit-limit: 10` for this key (C). `exclude=fullText` keeps replies to about 15 KB for 5 works (C).
- CORE's plain-word search covers full text: "momentum" with "india" returned a nutrition-policy chapter first (C). `abstract:"word"` terms for each topic word, plus `abstract:"stock" OR abstract:"equity"` and `yearPublished>=2015`, gave on-topic titles: 62 hits for "52-week high momentum", all five shown on topic (C). `abstract:(w1 w2)` grouping returned 0 (C).
- Semantic Scholar: key as `x-api-key`; "the introductory rate limit for an API key is 1 RPS on all endpoints" (B). The key is valid: a made-up key gets 403, ours 200 (C). The relevance search answered 429 to the first two calls and 200 to a later one 10 s on; bulk search answered 200 but ranks by keyword, not relevance (C).
- OpenAlex with the key: `X-RateLimit-Limit-USD: 1`, cost $0.001 a search (C), against $0.10 a day keyless (research 124).
- On "short-term reversal Indian equities" and "52-week high momentum India", CORE added 7 and 8 papers, Semantic Scholar 10 and 7, with no failures; most had abstracts of 600–2,500 characters; three Semantic Scholar results had none (D). arXiv returned none for either topic (D).

## Decision

ADR-131: both added as sources with keys in headers; CORE 6 s apart, Semantic Scholar 1 s apart with two retries on 429; keys read under both names.

## Confidence

Medium. Limits are from one day's headers and pages; the 429s from Semantic Scholar may be a shared-pool effect that changes.

## Open questions

- Whether CORE's limit is 10 or 25 a minute for this key (A says 25, C showed 10). A-100.
- CORE abstracts come from repositories and may be the publisher's copyright; like Crossref's, they are sent to the model only, never written to the repository.
- arXiv's strict `AND` query found nothing on these two topics; not changed here.
