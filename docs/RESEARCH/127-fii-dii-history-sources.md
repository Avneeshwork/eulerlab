# 127 — Where can a year of daily FII/DII cash flows come from?

**Date:** 2026-10-30 · **Confidence:** high that the Trendlyne series is NSE's provisional figure (it matches NSE and two other aggregators to within 0.05 crore); high on what the terms say (read directly); low on whether NSE held a session on Sunday 1 Feb 2026 (not checked)

## Question

NSE serves only the latest FII/DII day (research 004). The operator asked for
at least a year of history, scraped from aggregator sites. Which site serves
it, in what form, and what do its robots.txt and terms say?

## Sources

Everything was fetched from the operator's Mac on 2026-10-30 with a normal browser User-Agent, one request at a time, at least 2 s apart.

| Source | URL | Result |
|---|---|---|
| Trendlyne monthly page | https://trendlyne.com/macro-data/fii-dii/latest/cash-pastmonth/30-Sep-2026/ | 200. Server-rendered. The table `cash-table-main-pastmonth` has its rows in a `data-jsondata` attribute: about 20 trading days ending on the URL's date, with FII and DII gross buy, gross sell and net, rounded to 0.1 crore. A Sunday in the URL (30-Nov-2025) works too. No separate JSON request is needed. |
| Trendlyne robots.txt | https://trendlyne.com/robots.txt | Does not block `/macro-data/`. Asks for `Crawl-delay: 1` for all bots (10 for GPTBot and ClaudeBot). |
| Trendlyne terms | https://trendlyne.com/terms/ | Section 6: "You may not resell, redistribute, broadcast or transfer the information or use the information in a searchable, machine-readable database unless separately and specifically authorized in writing". The same wording research 004 read on 2026-08-18 (ADR-009). |
| Groww | https://groww.in/fii-dii-data | 200. `__NEXT_DATA__` `pageProps.initialData` holds 20 days of `fii` and `dii` `grossBuy`, `grossSell` and `netBuySell` at 0.01 crore. |
| Groww robots.txt | https://groww.in/robots.txt | Does not block `/fii-dii-data`. |
| Groww terms | https://groww.in/terms-and-conditions/ | Users "shall not copy, reproduce, sell, redistribute, publish, reverse engineer, enter into a database ... any part of any information" except for "Your own personal, internal, non-commercial use". |
| stockezee | https://stockezee.com/fii-dii-historical-data | 200. `__NEXT_DATA__` `initialData` holds 245 days (2025-11-03 to 2026-10-29) of FII and DII cash **net only**, plus derivatives figures. |
| stockezee robots.txt | https://stockezee.com/robots.txt | `Allow: /`, `Disallow: /api/`, for all bots including ClaudeBot. |
| stockezee terms | https://stockezee.com/terms | "You may access this from StockeZee for your own personal use". You must not "Reproduce, duplicate or copy material", and must not use the content "for commercial purposes without written permission". |
| Moneycontrol FII/DII page and robots.txt | https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/index.php | **403** for both. Not tried again (ADR-089: stop on 403). Its terms were not read. |
| niftytrader | https://www.niftytrader.in/fii-dii-data | 200, with dates back to 2020. Not parsed and its terms not read: Trendlyne already covered the year. |
| NSE | https://www.nseindia.com/api/fiidiiTradeReact | 200 for the API. The home page answered 403, but the API did not need its cookie. Returns 29-Oct-2026, categories `DII` and `FII/FPI`, numbers as strings. This settles A-070. |

## Findings

1. Trendlyne serves the history: 13 pages (Oct 2025 to today) gave 264 days, 2025-10-01 to 2026-10-29. With NSE's own 29 Oct that is 265 days. Every one of the 265 days in that span with a landed NSE cash bhavcopy has a row, and there are no others.
2. The three aggregators agree with each other and with NSE. The largest gap was 0.05 crore: Trendlyne against NSE on 1 day, against Groww on 20 days, and against stockezee's nets on 244 days. No figure differed by more than 1 crore.
3. Trendlyne rounds each figure to 0.1 crore, so net can differ from buy minus sell by up to 0.15 (for example 15-Sep-2026). NSE's 0.05 tolerance would refuse correct rows, so Trendlyne rows use 0.15.
4. Trendlyne and stockezee both show a session on **Sunday 1 Feb 2026** (Union Budget day). Trendlyne gives FII buy 598.3, sell 1186.6; DII buy 14390.8, sell 15073.5. EulerLab has no cash bhavcopy for that day, so the row was refused. Either NSE held a special session and the bhavcopy backfill missed it, or both sites are wrong (T-4189).
5. Every site that worked forbids storing its data in a database, unless it is for personal use or the site agrees in writing. None of their robots.txt files blocks the pages, which is not permission.

## Not found

- No site states which NSE release its figures come from. Trendlyne's page does not say "provisional"; the match with NSE is the only evidence (A-072).
- Moneycontrol could not be read (403), and its terms are unread.
- Nothing here gives the FII/DII figures for BSE alone, or NSDL's final FPI figures (T-4186).

## Decision

Backfill from Trendlyne, and cross-check against Groww and stockezee, by operator decision (ADR-089). `make fii-dii-history MONTHS=12`.
