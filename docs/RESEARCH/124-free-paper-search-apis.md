# 124 — Where can an agent find market papers for free, and on what terms?

**Date:** 2026-10-29 · **Confidence:** high on arXiv's terms and OpenAlex's pricing; medium on two OpenAlex field paths (A-065)

## Question

The paper agent (ADR-084) needs a search that returns real papers with real
links and abstracts, at no cost and with no scraping. Which services, which
limits, which fields?

## Sources

| Source | URL | Fetched | Type |
|---|---|---|---|
| arXiv API User's Manual | https://info.arxiv.org/help/api/user-manual.html | 2026-10-29 | official docs |
| arXiv, Terms of Use for APIs | https://info.arxiv.org/help/api/tou.html | 2026-10-29 | official terms |
| OpenAlex, Authentication & Pricing | https://developers.openalex.org/api-reference/authentication | 2026-10-29 | official docs |
| OpenAlex, Search guide | https://developers.openalex.org/guides/searching | 2026-10-29 | official docs |
| OpenAlex, Work attributes | https://help.openalex.org/data/works/attributes/ | 2026-10-29 | official docs |
| OpenAlex, LLM quick reference | https://help.openalex.org/api/llm-quick-reference/ | 2026-10-29 | official docs |

## Findings

1. **arXiv:** `export.arxiv.org/api/query` with `search_query` (prefixes `ti`,
   `abs`, `au`, `cat`, `all`; `AND`, `OR`, `ANDNOT`), `start`, `max_results`,
   `sortBy`, `sortOrder`. Atom entries carry `id` (abstract page), `title`,
   `summary` (the abstract), `published`, `author/name`, a `pdf` link and
   `arxiv:primary_category`. No key.
2. **arXiv terms:** no more than one request every three seconds, on one
   connection, across every machine you control. Metadata is CC0. E-prints may
   be retrieved and stored for personal or research use but not served from
   your own servers. The paper agent stores no paper text.
3. **OpenAlex:** `api.openalex.org/works?search=...` searches title, abstract and
   full text. Search costs $1 per 1,000 calls. Without a key the daily budget is
   $0.10, which is 100 searches. A free key (`api_key=`) raises it to $1. Over
   100 requests a second returns 429. `per_page` is at most 100. Filters are
   `filter=publication_year:>2020,type:article|preprint`.
4. **OpenAlex abstracts** come as an inverted index (`{word: [positions]}`),
   "for legal reasons", and have to be rebuilt. The index sometimes includes
   trailing text that is not part of the abstract.
5. **Full text.** arXiv's HTML rendering (`arxiv.org/html/<id>`) is text that can
   be read without a PDF parser. The agent uses it when it exists, cut to
   16,000 characters, so the request fits Groq's 8,000 tokens a minute
   (research 123). Otherwise the agent reads the abstract and says so on the
   draft.

## Decision

ADR-084: arXiv and OpenAlex, both by default. Results are kept one per title.
arXiv is limited to `q-fin` categories. OpenAlex covers journals, including
Indian finance journals that arXiv does not.

## What I could not verify

- Whether arXiv's `cat:` accepts a `q-fin.*` wildcard. The manual documents
  `cat:` but not wildcards (A-064). If it does not, the query returns nothing
  and the run says no papers were found. It does not fail silently.
- The OpenAlex paths `primary_location.landing_page_url` and
  `authorships[].author.display_name`. The attribute page points to other pages
  for both, and those were not fetched (A-065).
- Neither API could be called from the build container, which blocks both
  hosts. The parsers are tested against responses written in the documented
  shapes (S-040), not against recorded live responses.
- SSRN has no public search API that was found. It is not used.

## Open questions

- Semantic Scholar's API as a third source. Not looked at.
