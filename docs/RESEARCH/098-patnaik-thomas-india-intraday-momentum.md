# 098 — Rechecking India's high-frequency momentum evidence

**Screen date:** 2026-10-15
**Disposition:** promising source; exact replication blocked; no strategy card added

## Source and claim

Patnaik and Thomas, *Profitability of Trading Strategies on High-Frequency Data, with Trading Costs* (2004), study NSE equities over 1996–2002 using intraday order-book data. Their abstract says they compute executable prices for ₹10,000 orders using order-book price impact, explicitly address microstructure effects such as bid-ask bounce, and find short-run momentum profitability after those effects, with profits declining as the formation period lengthens. This is unusually relevant Indian evidence because the reported test attempts to account for execution costs rather than merely comparing candle closes.

The full paper PDF linked from SSRN currently returns HTTP 403 in this environment. The accessible abstract does not identify the exact formation/holding intervals, portfolio construction, securities, trade frequency, or result tables. We should not invent those details or quote a return figure. The source is added to the Research Library with `idea` status, not represented as a reproducible strategy.

## Deduplication and local feasibility

The broad momentum family already appears in the library: rest-of-day momentum, opening-half-hour same-time continuation, opening-range continuation, volume-spike momentum, and EMA/Supertrend continuation. Patnaik and Thomas' high-frequency NSE order-book result is a distinct *source and execution-aware question*, but not yet a sufficiently specified distinct rule/card. Once its full method is available, compare the actual formation and holding intervals against those registered rules before coding.

This checkout has one-minute OHLCV for a wide NSE universe, but not historical best bid/offer, book depth, order queue, or sequence-level trades. Therefore it cannot reproduce the paper's own cost/impact method. A price-only adaptation could be screened with the project's fee router and assumed slippage, but that would not validate the paper's claim and would overlap existing momentum studies unless the paper reveals a materially different formation/holding rule. The existing strategy screens already show that small gross candle effects often fail Indian cash-equity costs.

## Decision and data needed

No new backtest or Strategy Library card is created from an abstract-only rule. Obtain the full paper through an authorized archive or author copy, then capture the exact rule and determine whether it is distinct. A faithful current-market test also needs historical NSE quote/order-book data, at minimum timestamped best bid/offer and depth sufficient to estimate impact for a fixed notional; OHLCV alone cannot do that. Any adapted candle-only test must be labeled separately, predeclare its rule, compare it to the existing momentum cards, and report the same net-of-cost and holdout standards as other candidates.

## Sources

- Patnaik & Thomas (2004), [Profitability of Trading Strategies on High-Frequency Data, with Trading Costs](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=568363). The PDF endpoint was inaccessible (403); claims above are limited to the abstract.
- Existing local momentum and cost results: [076 — Five intraday rules from Indian sources](076-five-indian-intraday-rules.md), [078 — Two stock rules on Indian stocks](078-two-us-stock-rules-on-indian-stocks.md), and [095 — GitHub EMA crossover NSE screen](095-github-ema-crossover-nse-screen.md).
