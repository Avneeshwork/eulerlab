# 144 — Why did the research agent draft nothing, and where can a missing abstract come from?

## Question

The operator, 2026-11-03: the research agent, looking for strategies, gives zero results. Its runs on 2026-11-01, 11-02 and 11-03 each said "0 drafted" after reading four or five papers, with no reason.

## Sources

- A. Crossref, "REST API", https://www.crossref.org/documentation/retrieve-metadata/rest-api/, fetched 2026-11-03.
- B. Crossref, "Tips for using the Crossref REST API", https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/, fetched 2026-11-03.
- C. Semantic Scholar Graph API, `https://api.semanticscholar.org/graph/v1/paper/DOI:<doi>`, called 2026-11-03.
- D. Measured: the paper agent re-run on "price momentum Indian stocks" with every paper's outcome printed (before and after the fix), and on "intraday stock trading strategies in Indian market" (after).

## Findings

- Before (D), of ten candidates for "price momentum Indian stocks": 1 drafted, 2 not relevant (with sound reasons), 2 known, 3 with no abstract, 1 failed because gpt-oss-120b wrote `implementation` as an object and the strict reply check dropped the paper ("An Analysis of Momentum Strategies in Indian Stock Returns", the most on-topic one), 1 failed on a 60-second Groq timeout. The real run on 11-02 drafted none; the model's verdicts vary between runs.
- When nothing was drafted, the run wrote no `run.json`, so neither the operator nor the next run saw why, and papers judged not relevant were read again on the next run of that topic.
- Off-topic hits use read slots: "Price Discovery in Indonesia Banking Stocks" for momentum; a brain-imaging neural network paper for "frog in the pan" (11-01).
- The three abstract-less papers were SSRN deposits. Crossref held an abstract for two of them, as JATS XML. Semantic Scholar answered 429 without a key for two and 404 for the third (C), so it is not usable keyless.
- Crossref needs no sign-up (A). "Almost none of the metadata is subject to copyright, and you may use it for any purpose", but "some abstracts contained in the metadata may be subject to copyright by publishers or authors" (A). Neither page states a rate limit; B says to back off on 429 and not to repeat requests.
- After (D): momentum, 2 drafted (including the paper lost before), 3 not a trading idea, 1 with no abstract anywhere; intraday (0 drafted on 11-03), 1 drafted, 4 not a trading idea (literature reviews, ML papers with no concrete rule). Ten papers added to the library copy.

## Decision

ADR-126: tolerant reply parsing, one retry, topic-ranked reading (A-097), a Crossref lookup for a missing abstract, every judged paper kept in the library, and every run's outcomes recorded and shown. A fetched abstract is sent to the model and never stored. No `mailto` is sent to Crossref, since it would carry the operator's address.

## Confidence

High on the causes (each paper's outcome printed). Medium that more drafts follow on other topics: most papers found for Indian topics are abstract-only and many are reviews.

## Not found

Crossref's request limits for unidentified callers. Whether OpenAlex withholds abstracts for SSRN works as a rule.

## Open questions

Whether to add a free OpenAlex key or Semantic Scholar key for more searches and abstracts.
