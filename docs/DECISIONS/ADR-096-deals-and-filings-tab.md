# ADR-096: A Deals & filings tab built from one nightly summary file

- **Context:** The operator asked for the useful parts of ScanX on the dashboard, from the NSE reports landed by ADR-095 (research 130).
- **Options:** (a) the API reads the landed reports on each request; (b) `make market-reports` writes `data/derived/market_reports.json` once a night and the API serves it as is; (c) a section inside `/api/market-context`.
- **Choice:** (b), as its own route (`/api/market-reports`) and its own India tab between Big money and Stocks to watch. It runs inside `make nse-reports`, after the download and before `upload-verified` deletes the local files, so it reads local bytes; a file already pruned is read back from B2.
- **Why:** The raw files leave the Mac the night they land, and reading them back on every page load would spend B2's 2,500 downloads a day. A separate route keeps a broken report from slowing the market context.
- **Cost if wrong:** The tab is a day behind until the evening job runs. SLBM column meanings and pledge field meanings are inferred (A-077, A-078). Insider rows have no size: NSE's list carries the filing, not the trade.
