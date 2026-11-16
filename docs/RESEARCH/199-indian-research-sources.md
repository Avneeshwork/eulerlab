# 199 — Which Indian research sources can the paper search read, and on what terms?

**Date:** 2026-11-16 · **Confidence:** high on what each page returned; medium on terms (SEBI's and RBI's are about websites, not data; NSE's could not be read)

## Question

Issue #159 asks for NSE working papers, IIM Ahmedabad, ISB, SEBI research and RBI bulletins and working papers in `paper_search`. For each: is there a listing a program can read, and do the terms allow a program to read it?

## Sources

All fetched 2026-11-16 from the Mac with a plain request (`curl`, no browser headers) unless marked WebFetch.

| Source | URL | Result |
|---|---|---|
| NSE robots.txt | https://www.nseindia.com/robots.txt | 200. `Allow: /`, only `/market-data-test` disallowed |
| NSE working papers | https://www.nseindia.com/research/working-papers | Plain request: no answer (status 000). WebFetch: timed out after 60 s. A search snippet shows a numbered list (newest Sr. No. 241, 2024) |
| NSE terms of use | https://www.nseindia.com/terms-of-use | Not reached (status 000; WebFetch timed out). **Not read.** |
| IIMA robots.txt | https://www.iima.ac.in/robots.txt | 200. Allows all but `/wp-admin/` and one working-paper PDF |
| IIMA working papers | https://www.iima.ac.in/faculty-research/working-papers | 404. The real listing was not found; https://iima.ac.in/faculty-research/research-publications mentions the series (search snippet only) |
| RePEc IDEAS, IIMA series | https://ideas.repec.org/s/iim/iimawp.html | 200, HTML. About 199 items 2016-2026 on page 1 of 14 (WebFetch) |
| RePEc data terms | https://ideas.repec.org/getdata.html (WebFetch) | Contributors' data is "not for commercial use"; commercial users must contact RePEc first; scraping the sites is strongly discouraged; the API is a fallback |
| ISB robots.txt | https://www.isb.edu/robots.txt | 200. `Allow: /` |
| ISB e-prints repository | https://eprints.exchange.isb.edu/view/type/monograph.html (search snippet: 393 working papers) | Listing exists |
| ISB OAI-PMH | https://eprints.exchange.isb.edu/cgi/oai2?verb=Identify | 200, OAI-PMH 2.0 (earliest record 2014-10-24). Fetched once, before its robots.txt was read |
| ISB e-prints robots.txt | https://eprints.exchange.isb.edu/robots.txt | 200. `Disallow: /cgi/`, which covers the OAI-PMH endpoint |
| SEBI robots.txt | https://www.sebi.gov.in/robots.txt | 200. Disallows only script and style folders |
| SEBI research page | https://www.sebi.gov.in/reports-and-statistics/research.html | 200. Links Working Papers, Investor Survey, DRG Studies, Research Papers/articles |
| SEBI working papers | https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=4&ssid=81&smid=104 | 200, HTML table. 10 papers, 1999-2004, PDFs, no abstracts |
| SEBI DRG studies | same, `smid=106` | 2 records (2014, 2015) |
| SEBI research papers/articles | same, `smid=109` | 11 records (2024-2026), mostly derivatives-trader studies, PDFs, no abstracts |
| SEBI website policy | https://www.sebi.gov.in/website-policy.html (WebFetch) | Direct links allowed. Material "may be reproduced free of charge after taking proper permission by sending a mail". Nothing on automated access |
| RBI robots.txt | https://www.rbi.org.in/robots.txt | 418 (refused) |
| RBI RSS list | https://rbi.org.in/Scripts/rss.aspx | 200. Lists Bulletin, Publication (annual report), press release, notification, speech and tender feeds |
| RBI Bulletin RSS | https://rbi.org.in/Bulletin_rss.xml | 200, RSS. Items are bulletin data tables (e.g. household financial assets), not articles |
| RBI working papers | https://www.rbi.org.in/Scripts/OccasionalPublications.aspx?head=Working%20Papers | 200, HTML by year. Newest: "RBI WPS (DEPR): 01/2026", 2026-10-09. No feed |
| RBI disclaimer | https://www.rbi.org.in/Scripts/Disclaimer.aspx (WebFetch) | "caching and links to, and the framing of this Web Site or any of the contents are prohibited"; links to inner pages need RBI's prior permission |
| OpenAlex, works filtered by Indian institutions | https://api.openalex.org/works?search=momentum%20stock%20returns&filter=authorships.institutions.country_code:in,publication_year:%3E2014,type:article%7Cpreprint | 200, JSON, 1,869 works; abstracts and `open_access.oa_url` present (some `null`, some DOI links, some publisher PDFs) |
| OpenAlex institutions | https://api.openalex.org/institutions?search=... | RBI `I1287339526` (1,040 works), ISB `I122328836` (1,878), IIMA `I150870154` (4,793), all `IN`. No institution found for NSE or SEBI |

OpenAlex's terms (metadata CC0, $0.10 of calls a day without a key) are in research 124. The OpenAlex response suggests an agent ask for a key with the user's email; that was not done.

## Findings

1. **No Indian source has its own machine-readable listing with terms that allow a program to use it.**
   - NSE: the listing exists but could not be reached from a plain request, and the terms of use could not be read. Not added.
   - IIMA: no listing found on its own site. RePEc lists the series, but RePEc's data is not for commercial use and it discourages scraping; a single operator trading own capital is close enough to commercial that this is not assumed to be allowed. Not added.
   - ISB: an OAI-PMH endpoint exists, but the repository's robots.txt disallows `/cgi/`, where it lives. Not added.
   - SEBI: an HTML table, linking allowed, reproduction needs permission by email. 23 items in all, PDFs without abstracts, most about derivatives (out of scope). Nothing the paper agent could read without a PDF reader. Not added.
   - RBI: the disclaimer prohibits caching and needs permission to link inner pages; the library stores a link per paper. The Bulletin feed is data tables. Not added.
2. **OpenAlex covers the institutions.** Filtering works by `authorships.institutions.country_code:IN` returns Indian-authored papers with abstracts, under the terms already accepted for OpenAlex. IIMA, ISB and RBI are OpenAlex institutions. This is added as the `india` source.
3. **Open-access copies are often PDFs.** Of the five Indian-authored momentum papers returned, two had no `oa_url`, two had a DOI link and one a publisher PDF. Without a PDF reader, most open copies still end as an abstract read.

## Decision

ADR-215. `paper_search.SOURCES["india"]`: OpenAlex filtered to Indian institutions, searched by the research agent. NSE, IIMA (own site and RePEc), ISB (OAI-PMH), SEBI and RBI are not searched, for the reasons above.

## What could not be found

- NSE's working-paper page and terms of use (not reached).
- IIMA's own working-paper listing (the expected address is a 404).
- ISB's terms of use for its repository, and whether the OAI-PMH `Identify` answer carries a metadata policy (the response was cut before that part; not re-fetched because robots.txt disallows it).
- Whether NSE or SEBI working papers are in OpenAlex under another name (no institution match).
- RBI's robots.txt (answered 418).

## Open questions

- Ask NSE or RePEc for permission, if the Indian working papers turn out to matter. Operator decision; no contact address was checked.
- A PDF reader (for example `pypdf`, pure Python) would turn many abstract reads into full-text reads. Not added: it is a new dependency and needs the operator's yes.
- `robots_allow` checks the robots.txt of the host in `oa_url`. A DOI link redirects to a publisher whose own robots.txt is not checked.
- These terms are recorded as A-162, recheck 2027-05-16.
