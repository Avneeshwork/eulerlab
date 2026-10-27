# 120 — What trader dashboards show, and what ours lacks

**Question.** What do established trading platforms put on their market
dashboard, and which of those analyses can EulerLab add from data it already
lands, without a new source or a paid feed?

All fetched 2026-10-27.

## Sources

| # | Source | What it is |
|---|---|---|
| 1 | https://blog.stockedge.com/markets-at-a-glance-stockedge-home | StockEdge's own description of its home screen |
| 2 | https://blog.stockedge.com/stockedge-version-13-3/ | StockEdge 13.3: 1/3/6-month momentum scores on breadth and sectors (via search summary) |
| 3 | https://blog.sensibull.com/2018/07/09/option-chain-tutorial/ | Sensibull's option chain metrics and its own caveats |
| 4 | https://blog.sensibull.com/2023/03/22/enhanced-sensibull-option-chain/ | Sensibull option chain update (search summary only) |
| 5 | https://finviz.com/ | Finviz home page, read through cached snapshots in search results, not fetched live |
| 6 | https://chartschool.stockcharts.com/table-of-contents/market-indicators/percent-above-moving-average | Definition and readings of % of stocks above a moving average |
| 7 | https://chartschool.stockcharts.com/table-of-contents/market-indicators/high-low-index | Record High Percent and High-Low Index |
| 8 | https://algotest.in/blog/participant-wise-open-interest/ | How NSE's participant-wise OI report is read, with caveats (secondary) |
| 9 | https://bseindia.com/markets/Derivatives/DeriReports/DeriMarketDisclosures.aspx | BSE's equivalent report and its Client definition (search summary) |
| 10 | https://help.tickertape.in | Tickertape Market Mood Index: six inputs (search summary) |
| 11 | https://www.luxalgo.com/library/concept/relative-rotation-graphs.md | Relative Rotation Graphs: concept; says the JdK smoothing is proprietary |
| 12 | https://tradingqna.com/t/ask-me-anything-nithin-karthik/196899?page=2 | Zerodha: FII/DII data is in Sensibull, not Kite (forum AMA, may be dated) |
| 13 | https://www.capitalmind.in/nifty-pe-ratio/ | Nifty PE moved to consolidated earnings in April 2021; 40.1 -> 32.7 (search summary) |
| 14 | https://primeinvestor.in/nifty-pe-ratio | Same switch, 40.3 -> 33 on 1 April 2021 (search summary) |

## Findings

**What the platforms show on the first screen.**
- **StockEdge [1]:**
  - Index strip (NIFTY 50, SENSEX, NIFTY 500, NIFTY Bank).
  - Price movers, volume shockers, 52-week and all-time highs and lows.
  - FII/DII cash and derivatives activity.
  - Sectors by market-cap change.
  - Deals (bulk, block, insider).
  - Upcoming results and corporate events.
  - In 13.3 [2], 1-, 3- and 6-month momentum scores for sectors and breadth.
- **Finviz [5]:**
  - Advancing/declining counts, new 52-week highs and lows, and the % of stocks above their 50- and 200-day averages.
  - Signal lists: gainers, losers, new high, new low, overbought, oversold, unusual volume, most volatile.
- **Sensibull [3]:**
  - PCR, max pain, ATM IV, IV percentile (current ATM IV against the last 250 days), OI by strike, and Greeks.
  - Its own caveats, quoted: "PCR, Max Pain and IV Percentile do not have high predictive power"; "They have meaning only if backed by high OI and high volumes"; "IVP does not have significance on the expiry week".
- **Tickertape [10]:** a single sentiment score built from FII positioning, volatility and skew, momentum, breadth, price strength and gold demand. It claims 93.75% accuracy, which is its own unaudited figure.

**Definitions we can use exactly.**
- **% above a moving average [6]:** the number of stocks above their N-day average divided by the number of stocks.
  - The 50-day whipsaws; the 150- and 200-day work better with 50% as the line.
  - "Readings above 70% are deemed overbought and readings below 30% are deemed oversold."
- **Record High Percent [7]:** new highs / (new highs + new lows) × 100. The High-Low Index is its 10-day simple moving average. Readings held above 70 coincide with strong uptrends, below 30 with strong downtrends.
- **Participant-wise OI [8, 9]:** an end-of-day NSE file with Client, DII, FII and Pro long and short contracts in index and stock futures and options.
  - "Client" is not retail alone.
  - A DII short future is often an arbitrage leg.
  - Netting across instruments does not give directional exposure. Index futures long ÷ (long + short) per participant is the reading the platforms use.

**What we could not find.**
- Koyfin's own documentation of its dashboard.
- TradingView's own India overview page.
- The exact RS-Ratio and RS-Momentum formula for Relative Rotation Graphs: it is proprietary [11], and every source we found is secondary.
- Any evidence that PCR, max pain or a mood index predicts returns. Sensibull says they do not [3]. Tickertape's 93.75% has no method published.
- FII/DII **cash** flows (provisional): not landed here. Only derivatives positioning is.

## What EulerLab already lands that its dashboard does not use

- `data/derived/index_history.jsonl`: 146 NSE indices daily since 2015, with PE, PB and dividend yield, India VIX and G-Sec indices. The snapshot's own gap list says "no index levels".
- `data/landing/nse/participant_oi/`: the participant-wise OI file, daily.
- `data/derived/delivery.jsonl`: delivered quantity per stock per day.
- `data/landing/option_chain/{NIFTY,BANKNIFTY,...}`: chain snapshots per expiry.
- `data/derived/nse_earnings_announcements.jsonl`: result dates.
- The price panel: enough for % above 20/50/200-day averages and 52-week highs and lows across about 2,700 stocks.

## Decision

Add, from landed data only:
- an index strip;
- breadth depth: % above averages, new highs and lows, Record High Percent;
- sector strength against NIFTY 50, using our own stated formula (not called an RRG, since that formula is proprietary);
- index valuation against its own history;
- F&O positioning: participant index-futures long share, PCR, ATM IV and its percentile, VIX;
- delivery-heavy movers;
- upcoming results.

Each figure shows its definition. Where the platform that made it popular says it has weak predictive power, that is shown too.

No composite "mood" score. It would add a number with no evidence behind it, which this project's evidence bar exists to refuse.

**Found while building (2026-10-27).**
- PE before April 2021 was on standalone earnings [13, 14], so PE is ranked only from that date (A-062).
- Liquid funds and ETFs (ISINs starting `INF`) drift to new highs almost daily and filled the new-high list. Breadth counts stocks only.
- No upcoming-results calendar is landed: `nse_earnings_announcements.jsonl` holds past filings and ends 2024-12-31. That item is replaced by new 52-week highs and lows among liquid names.
- 1,762 of 1,773 participant files are in the bucket at `nse/participant_oi/...`. Listed as the `nse` tree, the reader asked for `nse/nse/...` and saw only the 11 local ones (T-4162).

**Confidence.**
- High on the definitions [6, 7] and the data on disk.
- Medium on what each platform shows: [1] and [3] are first-party, the rest are secondary summaries.

**Open questions.**
- Whether FII/DII provisional cash data should be landed: a new source, and its own task.
- Whether any of these readings carries information here: each is a hypothesis to test through the gate, not a signal.
