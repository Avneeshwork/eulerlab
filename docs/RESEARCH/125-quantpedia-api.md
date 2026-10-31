# 125 — Can Quantpedia's API feed the research agent, and on what terms?

**Date:** 2026-10-29 · **Confidence:** high on the endpoints and auth (official docs); low on limits and pricing (not published)

## Question

The operator asked to include Quantpedia's API as a research resource, after
its article on building an AI research assistant. What does the API return,
how is it authenticated, and what does it cost?

## Sources

| Source | URL | Fetched | Type |
|---|---|---|---|
| Building an AI-powered quant research assistant with Quantpedia API | https://quantpedia.com/building-an-ai-powered-quant-research-assistant-with-quantpedia-api/ | 2026-10-29 | vendor article |
| Quantpedia API v1 docs | https://quantpedia.com/api/v1/docs#overview | 2026-10-29 | official docs |

## Findings

1. Base `https://quantpedia.com/api/v1`. HTTP Basic auth: Quantpedia username and an API key as the password.
2. `GET /strategy` lists every strategy visible to the account: `id`, `name`, `path`. No pagination is documented.
3. `GET /strategy/{id}`: name, description, `paperMetrics` (the paper's backtest years, performance, volatility, max drawdown, Sharpe), `calculatedMetrics` (Quantpedia's own recalculation, e.g. `sharpeRatioInception`), keywords, instruments, market factors, regions, complexity, confidence, crisis-hedge class, rebalancing period, transaction-cost notes, robustness checks, `sourcePaper` and `otherPapers` (`name`, `abstract`, `sources`, `fileId`).
4. `GET /strategy/{id}/performance` (equity curve; empty outside their Portfolio Analysis set, 404 without the permission), `/source-code`, and `GET /paper/{fileId}` (PDF).
5. Access is for Quantpedia Pro subscribers who ask for a key. The article gives no price; the pricing page was not fetched.

## What could not be found

Rate limits, quotas, error codes and the price of API access. Whether the list is paged for large accounts.

## Decision

`research/quantpedia.py` lands the list and each strategy's detail once, under `data/landing/quantpedia/<day>/`, with a SHA-256 manifest; `make quantpedia-sync` fetches at most 50 new details per run with a one-second pause (A-069). The research agent turns landed strategies close to its topic into "lead" items, and the knowledge index makes them searchable. Their Sharpe ratios are labelled as theirs: prior evidence, never a result here, and no trial is spent.

**Cost:** a Quantpedia Pro subscription, which the operator says they hold. Nothing else depends on it; without a key the sync says so and the agents carry on.

## Open questions

- Their recalculated Sharpe is on their own data and costs; how far it differs from Indian costs is unknown.
- The terms of use for storing API responses locally were not read (S-045).
