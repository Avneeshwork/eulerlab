# 083 — More intraday stock data for India

**Checked:** 2026-10-15
**Question:** Does EulerLab need another Indian stock intraday source, and which source can add useful minute history or execution detail?

## Current local coverage

The landed Kite minute archive contains 420 NSE symbols, 29,647 chunks, and 372,941,034 rows, dated through 2026-10-14. The first chunks for 411 symbols start on 2021-08-19; the other nine start later. The archive is broad and already supplies nearly five years of one-minute bars for most of its universe. It does not make the universe point-in-time: choosing today's symbols to form a historical portfolio can still create survivorship bias.

Kite's historical endpoint supports minute candles and accepts date ranges, but expired derivative tokens must be preserved separately to retrieve their histories. This is a better existing source than a new broker feed for 2021 onward; use another provider to add a genuinely earlier period or to check bar quality.

## Sources and findings

| Source | What it adds | Limitation / finding |
|---|---|---|
| [Zerodha Kite historical candles](https://kite.trade/docs/connect/v3/historical/) | Minute OHLCV candles for NSE instruments; already landed in EulerLab. | Current cache is 420 symbols from 2021-08-19 for 411 of them. No need to duplicate the same window without a validation reason. |
| [TrueData Market Data API](https://www.truedata.in/products/marketdataapi) and [historical-data support answer](https://feedback.truedata.in/topic/can-i-able-to-extract-200-symbol-data-at-time) | Vendor advertises NSE cash historical data and says in a support answer that historical NSE symbol data starts 2020-02-01, request windows are limited to 30 days, with 1-minute bars available. That could extend most of the local history by roughly 18 months and offer a second-source comparison. | The archive-start claim is in a vendor support response rather than the current API product specification; current coverage, price, adjustment convention, and licensing need a sample and written quote. Do not assume every historical symbol is present. |
| [NSE Data & Analytics historical products](https://www.nseindia.com/static/market-data/eod-historical-data-subscription), [technical specification](https://nsearchives.nseindia.com/web/mediaattachment/2026-01/NSE_Hist_Order_Trade_Data_117_20260105112141.pdf), [domestic tariff effective 2026-04-01](https://nsearchives.nseindia.com/web/mediaattachment/2026-04/Download_Pricing_file_-_Domestic_clients_20260424122229.pdf) | Exchange-sourced trade ticks can support independently aggregated minute bars and finer event studies. NSE's specification describes cash-market trade data at all-trade-tick frequency. | Domestic historical trade data for Capital Market is listed at ₹110,000 per annum per single site, before applicable taxes. The richer Historical Order & Trade Data is listed at ₹1,250,000 per annum per single site. Confirm coverage years, fields, permitted use, and delivery terms before purchase; this is a costly route. |
| [Angel One SmartAPI historical candles](https://smartapi.angelone.in/docs) | NSE stock minute candles; one request allows up to 30 calendar days (and the documented endpoint limits minute responses to 8,000 records). | A per-request window is not a promise of deep historical retention. It is not a meaningful extension until a dated old-history probe succeeds. |
| [Global Datafeeds historical coverage](https://globaldatafeeds.in/global-datafeeds-apis/global-datafeeds-apis/introduction/type-of-data-available/) | Independent NSE cash feed with minute bars and other intervals. | Published backfill depth for 1-minute NSE cash is three calendar months, so it is mainly useful for recent overlap validation, not extending multi-year tests. |
| [Accelpix plans](https://accelpix.com/pricing/) | Another independent feed with adjusted 1-minute data. | Published plans show 45–120 calendar days of 1-minute history; the listed Ultimate plan is ₹3,499/month plus GST and offers 120 days. That does not improve the five-year span. |

## Decision

The next sensible check is a **read-only TrueData sample request** for a handful of liquid names over the claimed 2020-02 to 2021-08 extension, plus the same dates in Kite's overlap. Compare timestamps, missing bars, OHLCV, corporate-action treatment, and symbol delistings/renames. Request written confirmation of current history depth, historic-universe coverage, price, and research/backtest licensing before subscribing.

If TrueData cannot supply usable older data, keep Kite for broad 2021-onward research. Treat NSE direct trade-tick data as a separate, higher-cost research proposal only if the strategy question needs trade-level execution or microstructure. Do not fetch a paid dataset or select a vendor based only on a product-page claim.

## Confidence and open questions

- **High:** local row/chunk/symbol counts from the manifest; published SmartAPI, Global Datafeeds, Accelpix, and NSE limits/pricing as seen on the checked pages.
- **Medium:** TrueData 2020-02 start and 30-day historical request limit, because the source is a vendor support answer and not a current product contract.
- **Open:** TrueData sample access, exact price and license; point-in-time symbol coverage and corporate-action treatment across vendors; whether NSE direct historical trade data is affordable for this single-operator research use.
