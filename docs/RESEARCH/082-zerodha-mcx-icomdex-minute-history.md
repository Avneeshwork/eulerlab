# 082 — Zerodha history for MCX iCOMDEX indices

**Date:** 2026-10-15
**Question:** Can Kite supply five years of one-minute history for the 12 MCX iCOMDEX indices in the operator's image?
**Decision:** Fetch every mapped series with confirmed history; record missing and empty series explicitly. Keep the full requested horizon in the ingest plan, but do not claim five years where Kite returned no candles.

## Source evidence

MCX's [iCOMDEX page](https://beta.mcxindia.com/market-data/mcx-icomdex-indices) lists the displayed indices and says the Nickel index was discontinued in January 2023. Nickel was not in the operator's image, so it is not part of this fetch.

Kite's [historical API documentation](https://kite.trade/docs/connect/v3/historical/) supports minute candles by instrument token. Its continuous endpoint is for expired futures and returns day candles; it does not describe index candles. The MCX indices below were therefore checked directly using their current MCX index tokens from Kite's instrument master.

The current instrument snapshot, fetched on 2026-10-15, contained tokens for Composite, Bullion, Base Metal, Energy, Gold, Silver, Copper, and several other MCX indices. A read-only historical probe sampled trading days in October 2021, October 2022, October 2023, October 2024, October 2025, and October 2026. Gold returned candles from the October 2022 sample; Composite, Bullion, Base Metal, Silver, Copper, and Crude Oil returned candles from the October 2024 sample. The Energy token returned no candles on any sampled date. These are confirmed starting samples, not a guarantee that earlier history never exists.

## Result

The full five-year scan queried each listed token from 2021-10-15 through 2026-10-14. It landed **1,811,889 one-minute candles** in **255 Parquet chunks**, about **29.9 MB**. Empty 60-day ranges are also recorded, so the next refresh does not request the same missing periods again. Seven series returned candles:

| iCOMDEX index | Kite symbol | Landed candles | Collection starts |
|---|---|---:|---|
| Composite | `MCXCOMPDEX` | 248,418 | 2024-02-05 |
| Bullion | `MCXBULLDEX` | 245,618 | 2024-02-05 |
| Base Metal | `MCXMETLDEX` | 237,438 | 2024-02-05 |
| Gold | `MCXGOLDEX` | 397,070 | 2021-10-18 |
| Silver | `MCXSILVDEX` | 234,886 | 2024-02-05 |
| Copper | `MCXCOPRDEX` | 220,965 | 2024-02-05 |
| Crude Oil | `MCXCRUDEX` | 227,494 | 2024-02-05 |

Gold has candles for the full five-year request. The other six available series begin on 2024-02-05 in the returned data. The other five requested indices are recorded as unresolved: Energy has a Kite token but returned no minute candles in any requested range; Aluminium, Lead, Zinc, and Natural Gas have no standalone tokens in Kite's current MCX instrument list.

The candle chunks, manifest, and unresolved list were uploaded to B2 under `nse/mcx_indices/`. A size check and SHA-256 metadata verification found all uploaded objects present and matching.

## Operations

`Tools → Instruments → Update all data` now runs **MCX index minute bars** when the Kite session was minted today. The step resumes from its manifest, fetches only missing 60-day ranges, and mirrors with the other data. `make mcx-index-minute` runs the same fetch directly; `make daily` mirrors `mcx_indices` after the fetch.

The coverage table reports the latest landed date and number of available series. The expected history is partial because Kite returned no data for the first 2 years and 4 months on six series, and returned no data for five indices. Do not use absent candles or indices as zero-valued series in a backtest.

## References

- [Kite historical candle API](https://kite.trade/docs/connect/v3/historical/)
- [Kite MCX index tokens from the instrument master](https://kite.trade/forum/discussion/14316/indices-instrument-token)
- [MCX iCOMDEX indices](https://beta.mcxindia.com/market-data/mcx-icomdex-indices)
