# 060 — Can jugaad-data give us option data we do not have?

**Question.** Fetch three months of option data from `jugaad-data` and land it;
also 1-minute bars if possible; also NIFTY 50 and SENSEX.

**Sources, fetched 2026-10-05.**

- `https://pypi.org/pypi/jugaad-data/json` — version 0.35.9, licence field
  "YOLO", deps requests/click/appdirs/bs4/lxml/brotli.
- `https://api.github.com/repos/jugaad-py/jugaad-data` — 583 stars, active,
  **`license: null`** and no `LICENSE` file (404). No licence means all rights
  reserved by default; the "YOLO" is a joke, not a grant.
- `jugaad_data/nse/history.py` — `derivatives_raw(symbol, from, to, expiry,
  instrument_type, strike, option_type)` against NSE `/api/historicalOR/foCPV`.
- `jugaad_data/nse/live.py` — `/option-chain-v3`, `/chart-databyindex`.
- Tested live against the real endpoints, not read from docs.

## Findings

**1. Three months of daily option data is already here, and is richer.**

Our F&O bhavcopy columns: `OpnPric HghPric LwPric ClsPric LastPric
PrvsClsgPric UndrlygPric SttlmPric OpnIntrst ChngInOpnIntrst TtlTradgVol
TtlTrfVal TtlNbOfTxsExctd NewBrdLotQty`.

`derivatives_raw` returns: `FH_OPENING_PRICE FH_CLOSING_PRICE
FH_LAST_TRADED_PRICE FH_PREV_CLS FH_SETTLE_PRICE FH_OPEN_INT FH_CHANGE_IN_OI
FH_MARKET_LOT` — a strict **subset**. No high, no low, no turnover, no trade
count.

**678 F&O days are already landed** (2024-01-02 to 2026-10-01), 63 of them in
the last three months. Scraping would have taken an hour against an
unsupported endpoint to obtain less than what was already in B2.

What was actually missing was the *parser*: it read settlement price, volume
and open interest and dropped the other eleven columns, so the gap looked like
missing data rather than an unfinished parse. Widened; nothing fetched.

**2. Intraday option data exists but cannot be backfilled.**

`/chart-databyindex` returned 2,070 points for one NIFTY contract at roughly
13-second spacing — finer than 1-minute. It serves **the current session
only**. So intraday can be recorded forward from today and cannot be recovered
for any day already past. Three months of 1-minute option history is not
obtainable from this source at any effort.

Kite does serve 1-minute option history, but needs a token minted daily and
its depth for expired contracts is short.

**3. SENSEX is not available here.** It is a BSE index; NSE's
`/option-chain-v3` has no records for it, and `jugaad_data.bse` exports only
`BSELive` with no option chain. A SENSEX chain needs a BSE source this project
does not have.

**4. NIFTY 50 options are NIFTY options** — the index option chain already
served (116 strikes, 4 expiries). Nothing to add.

## Decision

Widen the bhavcopy parser; fetch nothing. Record intraday forward if wanted,
with the understanding that it starts empty.

## Confidence

High on 1, 3 and 4 — each tested against the live endpoint and against the
landed files. High on 2, with the caveat that NSE may change
`/chart-databyindex` without notice; it is an undocumented website API.

## Open

Whether BSE publishes an equivalent bhavcopy for SENSEX options, which would
be the clean way to get them rather than scraping.
