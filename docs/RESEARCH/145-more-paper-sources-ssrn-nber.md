# 145 — Which more sources of strategy papers can the research agent search, and how is one paper recognised under many links?

## Question

The operator, 2026-11-03: "ensure to not duplicate papers already available and keep increasing source of strategy research like SSRN etc."

## Sources

- A. SSRN terms of use, https://www.ssrn.com/index.cfm/en/terms-of-use/, fetched 2026-11-03: HTTP 403.
- B. SSRN robots, https://papers.ssrn.com/robots.txt, fetched 2026-11-03: a "Content Blocked" page.
- C. OpenAlex sources search, `https://api.openalex.org/sources?search=SSRN` and `?search=NBER working paper`, called 2026-11-03.
- D. OpenAlex, "Filter works", https://help.openalex.org/api-entities/works/filter-works, fetched 2026-11-03.
- E. Crossref works search, `https://api.crossref.org/works?query.bibliographic=...&filter=prefix:<prefix>`, called 2026-11-03 for 10.2139 (SSRN) and 10.3386 (NBER).
- F. OpenAlex works by DOI, `https://api.openalex.org/works/doi:10.3386/w25551` and three more, called 2026-11-03.
- G. Measured: the paper agent's search and run on "momentum strategies Indian stock market" with all four sources (D-F), on copies of the library and drafts.

## Findings

- SSRN refuses automated access to its own site (A, B), so it is not fetched directly.
- OpenAlex indexes SSRN as source `S4210172589`, "SSRN Electronic Journal", 1,374,524 works (C). Searched with `primary_location.source.id` (D), "price momentum India" gave 496 works, the top five on topic, none with an abstract (C).
- Crossref holds SSRN abstracts for many works (research 144) and, by prefix, found 20,295 SSRN works for that query, several listed twice under different DOIs: SSRN gives a revision a new DOI (E).
- OpenAlex has no usable NBER source (0 works, C). Crossref by prefix 10.3386 found 348 NBER works on topic, none with an abstract (E); OpenAlex had the abstract for all four NBER DOIs tried (F).
- Semantic Scholar answered 429 without a key (research 144); CORE needs a key. Neither is used.
- Sorted by topic overlap alone, OpenAlex's papers (with abstracts) took all five reads; with the sources taking turns, a run read and drafted from all three (G): 5 drafted, 2 from SSRN, 1 from NBER.
- The library held no duplicates by DOI, arXiv, SSRN or NBER number, title or near title (`make papers-duplicates`, 2026-11-03).

## Decision

ADR-129: sources `ssrn` (OpenAlex, SSRN filter) and `nber` (Crossref, prefix 10.3386) beside arXiv and OpenAlex, listed in `config/agents/research.yaml`; a missing abstract from Crossref, then OpenAlex; one paper recognised by DOI, arXiv number, SSRN number, NBER number, title, or a near-identical title (A-099); sources take turns at the reads.

## Confidence

High that both sources work keyless today (called live). Medium on the near-title threshold.

## Not found

Crossref's and OpenAlex's request limits for SSRN-filtered searches stated as such; OpenAlex says $0.10 of calls a day without a key (research 124). Whether SSRN's terms permit use of its metadata via third-party indexes (they could not be read; the metadata comes from OpenAlex and Crossref under their terms).

## Open questions

A free OpenAlex key raises the daily allowance. RePEc has no API; CORE and Semantic Scholar need keys.
