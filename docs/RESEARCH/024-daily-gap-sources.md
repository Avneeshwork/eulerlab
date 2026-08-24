# 024 — Sources that fill the daily gap, per dataset

**Question.** Every archive here stops short of today, each for a different
reason. What fills each gap, and does it exist?

**All probed 2026-08-24.** Nothing below is proposed without being fetched.

## The gaps, and what closes them

| Dataset | Where it stopped | Why | Source that fills it | Verified |
|---|---|---|---|---|
| Crypto 1m | 2026-07-31 | Binance publishes months **after they end** | **Binance daily archive** | 70,164 bytes for `BTCUSDT-1m-2026-08-23.zip`, with checksum |
| FX 1m | 2026-08-14 | FXCM stopped publishing weeks 33+ | **Dukascopy ticks** | `EURUSD 2026/07/21 10h` = 8,780 bytes |
| FX daily | 2026-08-14 | as above | **FMP EOD** | 1,374 rows, newest **2026-08-24** |
| Crypto daily | 2026-07-31 | as above | **FMP EOD** | 1,826 rows, newest **2026-08-24** |
| US equity daily | never held | no ingest | **FMP EOD** | AAPL 1,253 rows to 2026-08-21 |
| India equity daily | current | — | NSE bhavcopy | already in `make daily` |
| India equity live | current | — | Zerodha | 500 instruments in 0.2s |

## What was actually wrong

Neither archive was stale in the sense of a job failing. Both were **as current
as their source allows**, and the sources publish in arrears:

- **Binance** posts a month once the month is over. `crypto_backfill` had just
  pulled 10.4 million candles and still could not reach August, because August
  does not exist as a monthly file until September. The same host publishes
  daily files that cover exactly that window — same format, same parser.
- **FXCM** simply stopped. Weeks 33, 34 and 35 of 2026 all return 404. Adding
  FX to `make daily` was still right, but it does not fix this: the job will
  fetch weeks as they appear and none are appearing.

Calling either "stale" pointed at the pipeline when the answer was in the
source's publishing schedule.

## FMP end-of-day is the general filler, with one hole

Free tier, verified per asset class: **crypto and FX are current to today**, US
equities and indices to the last close. **India is 402 Payment Required** —
both `RELIANCE.NS` and `RELIANCE.BO`.

That hole does not matter, because India is the one market already covered:
NSE's own bhavcopy is free, official, and already in the daily job. FMP fills
what NSE does not publish and NSE fills what FMP will not sell.

## Built

`make crypto-fill` — Binance daily archive, in `make daily` ahead of the sync.
First run landed **636 symbol-days and 915,840 candles across 28 symbols with
nothing missing**, and `alt_panel.crypto_daily` reads them without a change
because day files sit beside month files and readers glob the folder.

## Not built, and why

- **Dukascopy FX gap fill.** The reader exists (`fx.py`). Ten pairs over ten
  days is 2,400 hourly requests — minutes, not the 245 days the full-history
  backfill measured. Worth doing; not started here.
- **US daily panel.** FMP EOD serves it at one call per symbol against a
  250/day budget, so a hundred-name universe is a staged backfill plus panel
  changes to hold a second market. A project, not an afternoon.
