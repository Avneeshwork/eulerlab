# 086 — Frozen intraday Gold rule on MCX futures

**Run date:** 2026-10-15
**Question:** Does the previously selected SMA(50) plus 20 bp dead band survive on actual MCX Gold futures?
**Answer:** No, on this short single-contract sample it loses 18.61% net of modeled charges and slippage.

## Source and data limits

Kite's historical API serves intraday candles by instrument token. Its continuous-futures option returns **daily** candles for expired MCX contracts; Kite says old derivative tokens are no longer available from the current instrument master unless they were archived while live. This repo has the 2026-10-15 MCX master but no older dated MCX masters. We therefore cannot reconstruct five years of minute bars from Zerodha alone. The continuous endpoint is not substituted for minute data. See [Kite historical API documentation](https://kite.trade/docs/connect/v3/historical/).

The live standard Gold contract `GOLD26DECFUT` (expiry 2026-12-04) returned 75,577 one-minute candles from 2026-04-14 through 2026-10-14 when requests included 09:00–23:55 IST. MCX describes standard Gold as a 1 kg contract; its price is quoted per 10 grams, so one quoted rupee point is ₹100 per lot. See [MCX Gold contract information](https://www.mcxindia.com/en/products/bullion/gold).

The source had 131 calendar trading sessions. We excluded 53 sessions with fewer than 150 observed five-minute bars (the full session had 174 bins in this sample), leaving 78 sessions for the backtest, 2026-05-14 through 2026-10-14. This removes the contract's sparse early history. The sample still covers one expiry only and does not test a roll.

## Frozen rule and execution

This applies the prior 2024-development choice from research [085](085-filtering-new-intraday-strategies.md), without retuning on MCX:

- SMA over the last 50 completed five-minute closes.
- Long when close is at least 20 bp above the SMA; short when at least 20 bp below; inside the band, keep the current side.
- Fill a change at the next five-minute open. Close any position at the session end.
- One standard 1 kg lot. P&L is shown against the opening contract notional, not account equity or margin.
- Current Zerodha commodity-futures charges: brokerage 0.03% capped at ₹20/order, MCX transaction charge 0.0021%, non-agri CTT 0.01% on sells, stamp duty 0.002% on buys, SEBI ₹10/crore and GST on brokerage/transaction/SEBI charges. We used the rates on [Zerodha's charges page](https://zerodha.com/charges/), checked 2026-10-15.
- Assumed slippage is 2 bp per side. No historical bid-ask or queue-position data is available.

## Result

| Measure | Frozen SMA(50) + 20 bp band | Long one-lot session benchmark |
|---|---:|---:|
| Sessions | 78 | 78 |
| Fills | 454 | 156 |
| Gross P&L | -₹905,700 (-5.82%) | +₹1,206,900 (+7.75%) |
| Modeled fees | ₹606,050 | included in net |
| Assumed slippage | ₹1,385,230 | included in net |
| Net P&L | **-₹2,896,980 (-18.61%)** | +₹523,456 (+3.36%) |
| Net daily Sharpe | -3.988 | 0.350 |
| Max drawdown | -21.44% | -13.10% |

The fixed rule underperformed both the intraday long benchmark and its own gross return after turnover costs. It is not supported for MCX Gold by this sample. The ETF result in research 085 remains a separate instrument and venue.

## Reproduction

```sh
make mcx-gold-minute
make mcx-gold-backtest
```

The fetcher saves minute files under `data/landing/mcx_gold/`; the fixed-result JSON is `data/derived/mcx_gold_backtest.json`. The make target also mirrors the fetched tree to B2. This result is a short historical screen, not a five-year MCX backtest, and not evidence of a durable edge.
