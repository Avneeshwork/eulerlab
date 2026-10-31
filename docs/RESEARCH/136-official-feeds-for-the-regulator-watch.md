# 136 — Which official feeds can the knowledge keeper read?

**Date:** 2026-10-31 · **Confidence:** high for the four feeds fetched from the Mac; none for MoSPI and AMFI, which have no feed.

## Question

Which official sources publish SEBI, RBI, NSE, MoSPI and AMFI notices in a form a daily job can read without a browser (ADR-104)?

## Sources

| Source | URL | Fetched | Result |
|---|---|---|---|
| SEBI RSS (press releases, circulars, orders) | https://www.sebi.gov.in/sebirss.xml (listed on https://www.sebi.gov.in/rss.html) | 2026-10-31 from the Mac | 200, RSS 2.0, 30 items; dates like "30 Oct, 2026 +0530" |
| RBI press releases RSS | https://rbi.org.in/pressreleases_rss.xml | 2026-10-31 | 200, RSS 2.0, BOM before the XML declaration, HTML in CDATA descriptions |
| RBI notifications RSS | https://rbi.org.in/notifications_rss.xml | 2026-10-31 | 200, RSS 2.0, same shape |
| NSE circulars RSS | https://nsearchives.nseindia.com/content/RSS/Circulars.xml (listed on https://www.nseindia.com/rss-feed) | 2026-10-31 | 200, RSS 2.0, 44 items, no session cookie needed |
| NSE's other feeds (announcements, board meetings, results, SAST, insider trading and more) | https://www.nseindia.com/rss-feed | 2026-10-31 | Listed; not used: company-level, not rule changes |
| MoSPI press releases | https://www.mospi.gov.in/press-release | 2026-10-31 | 200 but a JavaScript page; no RSS found |
| AMFI monthly data | https://www.amfiindia.com/research-information/amfi-monthly | 2026-10-31 | 200 but a JavaScript app; no RSS found |

RBI feed addresses came from a third-party feed directory (Feeder) and were confirmed by fetching them.

## Findings

1. Four official RSS feeds work with a plain request: SEBI, RBI press releases, RBI notifications and NSE circulars.
2. On the first run (94 items), matching keywords in titles and descriptions linked 20 items, most wrongly: descriptions carry boilerplate, and enforcement orders and single-stock F&O notices matched the rule pages. Matching titles only, with routine titles skipped, linked 4. All 4 were rule changes: FPI KYC review periodicity (two items), NSE's settlement price SOP, and the encumbrance measure.
3. MoSPI and AMFI have no feed. Economic calendar events still come from ForexFactory.

## Decision

Watch the four feeds daily; match titles only; skip enforcement and routine titles (`config/knowledge_sources.yaml`). MoSPI and AMFI are not watched (T-4256).

## Open questions

- Whether PIB's RSS carries MoSPI releases reliably (not checked).
- How often SEBI's feed drops items before a daily run sees them (it lists about 30).
