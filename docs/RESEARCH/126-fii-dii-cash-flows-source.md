# 126 — Where should FII/DII cash flows come from: scanx.trade or NSE?

**Date:** 2026-10-29 · **Confidence:** high that NSE is the publisher (research 004); low on scanx's contents and terms (not read); medium on NSE's field names (A-070)

## Question

The operator asked for a scraper for everything on
`https://scanx.trade/insight/fii-dii-data` that EulerLab does not hold, and for
it on the dashboard. What does that page add, may it be scraped, and is there
a better source for the same figures?

## Sources

| Source | URL | Fetched | Result |
|---|---|---|---|
| scanx FII/DII page | https://scanx.trade/insight/fii-dii-data | 2026-10-29 | **not read**: proxy 403 from the cloud container and from the operator's machine VM; the web fetch tool reported a client error |
| scanx robots.txt | https://scanx.trade/robots.txt | 2026-10-29 | **not read**, same |
| scanx launch post (Dhan community) | https://madefortrade.in/t/now-live-fii-dii-market-data-on-scanx-insights/33795 | 2026-10-29 | title and date only (18 Oct 2024): "FII & DII market data on ScanX Insights" |
| NSE FII/DII endpoint | https://www.nseindia.com/api/fiidiiTradeReact | 2026-10-29 | **not reachable** from this session (proxy 403). Read live on 2026-08-17 in research 004 |
| nsepython source (public client) | https://huggingface.co/spaces/eshan6704/backend/blob/main/nsepython.py | 2026-10-29 | calls `https://www.nseindia.com/api/fiidiiTradeReact` and returns it as a table; field names not in the copy read |
| Research 004 | docs/RESEARCH/004-india-macro-data-sources.md | 2026-08-17/18 | NSE serves the latest day only; `?date=` is ignored; no NSE archive; Trendlyne terms bar database use |

## Findings

1. scanx.trade is Dhan's market-data site. The launch post calls it FII and DII
   market data; its contents beyond that could not be read.
2. The provisional FII/DII cash figure has one publisher: NSE, each evening,
   for that day only. Every aggregator found in research 004 (Trendlyne, Groww,
   StockEdge, Moneycontrol) republishes it and keeps its own archive.
3. The derivatives side most such pages show (FII/DII/Pro/Client positions in
   index and stock futures and options) is NSE's participant-wise OI, which
   EulerLab has landed daily since 2020.
4. NSDL publishes daily FPI investment reports and an archive (research 004,
   065). Format and terms not read.

## What could not be found

- scanx.trade's page content, its terms and its robots.txt. **Not read is not
  permission**; ADR-009 records the same lesson from Trendlyne.
- Whether scanx shows anything NSE does not publish (for example FII
  derivatives turnover by instrument, NSE's `fii_stats` report). Not checked.
- NSE's exact field names, from NSE itself, in this session (A-070).
- The time NSE publishes the figure each evening. `make daily` (19:30) and
  every `make india-live` pass until 21:00 both try.

## Decision

Capture NSE's figure directly, forward only (ADR-088). Do not scrape scanx.
Backfill from NSDL is a separate task once its terms and format are read
(T-4186). Compare scanx's page with what EulerLab holds when it can be opened
(T-4187).

## Open questions

- Does NSE publish before 19:30 on most days? Answered by the landed files'
  knowledge times after a few weeks.
- Do NSE's figures ever change after first publication? A second capture the
  same evening would show it; today a held day is skipped.
