# 121 — Making the dashboard easy to read

**Question.** After research 120 added the figures, the operator found the page
hard to read and asked for clearer UI, more useful tabs, and the Breadth band
replaced. How do retail-facing platforms make the same figures readable?

All fetched 2026-10-27.

## Sources

| # | Source | What it is |
|---|---|---|
| 1 | https://tickertape.in | Tickertape home: opens with "The market is in Fear zone" (Market Mood Index), then "Market and sectors", then stock lists (search snapshot) |
| 2 | https://upstox.com/fii-dii-data/ | Upstox FII/DII page, fetched: tabs Cash / Index Futures / Stock Futures / Index Options / Stock Options; "FII long value %" and "short value %"; plain definitions of FII and DII on the page |
| 3 | https://lollypop.design/blog/2026/may/investment-dashboard-ux-design-guide/ | Practitioner guide, fetched: summary first and pinned; layered detail; colour paired with arrows; "never show a loss without a comparison"; plain-language labels |
| 4 | https://fanruan.com/en/blog/enhance-investment-dashboard-for-maximum-clarity | "Show summaries first, then details if needed" (search summary) |
| 5 | https://www.business-standard.com/markets/news/analysts-flag-caution-as-fiis-net-short-diis-up-f-o-sell-side-bets-by-200-125052200221_1.html | Long-short ratio in index futures: "a ratio of 0.6 implies presence of nearly 2 short positions for every long"; FII 0.09-0.11 read as heavy short bets (search summary; the page returned 403) |
| 6 | https://apps.apple.com/us/app/-/id408654600 | Moneycontrol app listing: FII/DII "graph enabled insights", FPI sectoral activity, OI participants (search summary) |

## Findings

- **A verdict comes first.** Tickertape's first line is a word: Fear, Greed [1]. The guides put the summary at the top and the detail below it [3, 4].
- **Numbers are explained where they stand.** Upstox defines FII and DII on the data page itself [2]. Its long and short columns are percentages, not contract counts.
- **Gains and losses are read against something:** "Never show a loss without a comparison" [3]. Market size bands (large, mid, small) and Nifty are the natural comparisons here.
- **Colour is never the only signal.** Arrows go beside red and green [3].
- **Detail goes in sections.** Upstox splits by instrument in tabs [2]; the guide uses accordions [3].
- **Not found:** any study showing that verdict words help traders decide better, or a regulator's plain-language guidance for market dashboards. Tickertape publishes no method for its mood label.

## Decision

- The India dashboard gets four tabs: **Overview, Sectors, Big money (F&O), Stocks to watch**.
- The Breadth band is replaced by **Market pulse**: four cards (Trend, Participation, Fear, Big money). Each has a word, an arrow, a colour and one plain sentence built from the figure, with the figure and its rule a click away.
- Unlike Tickertape's mood index, there is no single combined score. Each card's rule is printed, with fixed thresholds stated as ours.
- An auto-written "what happened today" paragraph comes from templates over the same numbers, not a language model, so every sentence traces to a figure.

**Confidence.**
- High that these are the patterns the platforms use: [1] and [2] are first-party.
- Medium that they make the page easier for this operator. Only the operator can judge that.
