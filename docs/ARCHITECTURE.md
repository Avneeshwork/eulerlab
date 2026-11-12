# How this system works

*A complete walkthrough for someone who has never seen this repository. It
assumes you can read English and follow arithmetic. It does not assume you know
finance, and every term is defined where it first appears.*

---

What each number on the platform means, what is normal for it and how to talk
about it is in `docs/METRICS/` (ADR-103), one page per metric; this file keeps
the maths.

## 0. What this is, in one paragraph

This is a **quant research and execution platform** for Indian equity markets,
built for one person trading their own money. It downloads market history,
cleans it, turns it into features, tests trading strategies against it,
subjects the survivors to statistical tests designed to catch self-deception,
and — if anything survives — places the orders. The whole system is organised
around a single uncomfortable fact: **it is very easy to produce a trading
strategy that looks excellent and is worthless.** Most of the code exists to
make that harder, not to make strategies.

---

## 1. The one idea you need first

If you take nothing else from this document, take this.

Suppose you test 20 random, meaningless strategies. Each is pure noise. The
*best* of those 20 will still look good — not because it works, but because you
looked 20 times. With enough attempts, an impressive backtest is the
**expected** outcome of nothing at all.

This is not a small effect. It is the dominant effect. It is why the system:

- **counts every strategy ever evaluated** in a tamper-evident ledger, and
  raises the bar for all future strategies as that count grows (§5.3);
- **splits data in ways that stop information leaking** from the test set into
  the training set (§5.1);
- **refuses to let you tune a failed strategy and resubmit it** (§5.8);
- **reads its final holdout data exactly once**, ever (§5.8).

Everything else is plumbing in service of that idea.

---

## 2. The shape of the system

Data flows left to right. Nothing flows backwards — a later stage never edits
an earlier one.

```
  NSE / broker            data/landing/            derived data
  ────────────            ─────────────            ────────────
  bhavcopy ZIPs   ──►     immutable raw     ──►    security master
  corporate actions       never edited             price panel
  minute bars             never deleted            adjustment factors
  fundamentals            hash-verified            feature values
        │                        │                        │
        │                        ▼                        ▼
        │                 Backblaze B2 mirror       ┌──────────────┐
        │                 (4.45 GB, 23,230 objs)    │  Strategy    │
        │                                           │  interface   │
        ▼                                           └──────┬───────┘
  bitemporal store ◄─── every record carries               │
  (the firewall)        event_time + knowledge_time        │
                                                    ┌──────┴───────┐
                                                    ▼              ▼
                                            Tier A screen    Tier B engine
                                            (fast, rough)   (orders, fills)
                                                                   │
                                    ┌──────────────────────────────┤
                                    ▼                              ▼
                            validation battery              order path
                            CPCV · DSR · PBO                OMS · EMS
                            stress · MinBTL                 reconciler
                                    │                       kill switch
                                    ▼                              │
                            promotion gate ────────────────────────┘
                            (operator-owned)                paper trading
                                    │                              │
                                    ▼                              ▼
                            holdout, read ONCE          reality-gap attribution
```

**The single most important structural fact:** a strategy is handed a
`MarketView` object containing only history up to its decision date. It cannot
see the future because the future is *not in the object it was given*. This is
called the **lookahead firewall**, and it is structural rather than a
convention — nothing has to remember to respect it.

---

# Part I — Data

## 3.1 The landing zone: raw data is immutable

Downloaded files land in `data/landing/` and are **never edited and never
deleted**. Every file is hashed on arrival; `make check-landing` re-hashes them
and proves nothing changed.

For locally pruned files, the check confirms the recorded size against B2.
Those listing requests use short timeouts, one attempt and a 15-second overall
deadline; an unreachable B2 is reported as unconfirmed data and fails closed
rather than stalling the check.

Why so strict? Because every number downstream is derived from these files. If
a raw file can be quietly "fixed", then a result can change without any code
changing, and no investigation will ever find out why. Immutable raw data means
any result is reproducible from first principles.

Local disk is not the storage of record — a Backblaze B2 bucket is (23,230
objects, 4.45 GB). Local copies are pruned once B2 confirms the upload.

`make mcx-instruments` fetches Kite's current MCX CSV once per IST calendar
day. It validates the exchange, token, symbol, lot size and tick size, then
lands the original response under `data/landing/mcx/` with a checksum and
knowledge time. The command mirrors that tree to the dedicated `nse/mcx/`
prefix in B2. This is a current contract snapshot; it does not create
historical MCX instrument or lot-size records. See ADR-075 and research 081.

### Market history: index closes, delivery, the calendar and expiries

Two more NSE daily files land beside the bhavcopies (`ingest/nse_daily_files`,
research 065): `ind_close_all` — open, high, low, close, volume, turnover, P/E,
P/B and dividend yield for **every NSE index**, India VIX and the sectoral
indices included — and `MTO`, the delivery position per security. `make
market-history` (`market_history.py`) turns the landing zone into four caches
under `data/derived/`. The two daily tables are extended by the days not yet
stored, because `make daily` prunes the local landing zone and re-reading
eleven years from B2 would spend its 2,500 downloads a day several times over
(`--full` rebuilds them):

| file | rows | knowledge time |
|---|---|---|
| `index_history.jsonl` | one line per day holding every index (177). NSE renamed most in November 2015 and spells some differently from file to file; `canonical_index` maps each old name to today's ("CNX Midcap" → "Nifty Midcap 100"), matched by closing level across the rename, so each index is one series | 20:00 IST that day (A-044) |
| `delivery.jsonl` | one line per day: per EQ-series stock, traded, deliverable, delivery % | 20:00 IST that day (A-044) |
| `nse_calendar.json` | trading days = dates with a landed cash bhavcopy; a holiday is a weekday between them without one; `weekend_sessions` (Saturdays and Sundays NSE opened) and `short_sessions` (panel turnover under 50% of its 20-session median, written by `make build-panel`) | — |
| `nifty_futures.jsonl` | one line per day: every live Nifty futures contract's open, high, low, close, settlement, open interest and volume, from the same F&O files, fetched over four connections | 20:00 IST that day |
| `nifty_expiries.json` | every Nifty futures expiry (144, 2015-2026), read from F&O bhavcopies fetched from NSE's archive every 15th trading day (each lists the next three monthly contracts). A file lists the *scheduled* date, which can move later, so each date is confirmed by its own day's file (`confirm_expiries`) | — |

**Special and short sessions (ADR-157, research 183).** NSE sometimes opens on
a Saturday or Sunday (Muhurat on Diwali, Budget day, disaster-recovery drills).
The nightly bhavcopy step probes weekends (`nse_eod --include-weekends`), and
every other NSE feed (index closes, delivery, participant OI, reports, Kite
minute bars) walks `nse_eod.session_days`: weekdays plus the weekend days whose
cash bhavcopy landed. A *short* session is a day whose total turnover is under
50% of the median of the 20 sessions before it (`master/sessions.py`): every
Muhurat, the 2024 disaster-recovery Saturdays and the late open of 2017-07-10. Its bar stays in the panel and in
signal history, but `vector.run`, `event_driven.run` (so paper books) and the
rule engine make no decision and no fill on it; positions are held through and
the next normal day decides and fills. A panel without turnover (US, crypto,
FX) or with fewer than 100 symbols flags nothing.

The price panel stored only the close before 2026-08-18. `make rebuild-ohlc`
re-reads every panel day's cash bhavcopy from NSE's archive (not B2, whose
2,500 downloads a day would take two days) through the same parser the panel
uses, and `SWAP=1` replaces the panel only if every stored close is reproduced
exactly; the close-only panel is kept beside it.

### NSE daily reports, index minutes and market depth (ADR-095)

`make nse-reports` (`ingest/nse_reports`, research 130) lands twelve NSE
reports raw under `data/landing/nse_reports/<report>/YYYY/MM/`. Eight are
dated, one file per trading day: bulk deals, block deals, short selling (all
from the archive API's CSV form, because its JSON form stops at 70 rows), the
F&O ban list, the SLBM bhavcopy, MTF, SEBI PIT insider filings and SAST
regulation 29 filings. Four are snapshots of today, since NSE keeps no history
of them: promoter pledges, open IPOs, past IPOs and the Nifty 50 constituent
list. A day is fetched once it is over: from 21:00 IST that day for the
end-of-day files, the next day for the filings NSE broadcasts late. A report in
the manifest is never fetched again, even after its local copy is pruned.

`make index-minute` lands Kite 1-minute candles for NIFTY 50, NIFTY BANK and
INDIA VIX under `data/landing/kite_index_minute/` (volume is always 0: an
index does not trade). `make depth-day`, run by the `depth` launchd job at
09:10 IST, records Kite's five-level depth for the 50 Nifty stocks, the index
and the nearest Nifty future until 15:31. Each row has `event_time` (the
exchange timestamp) and `knowledge_time` (when the Mac received it). This is a
snapshot per change, not NSE's order feed (S-052), and starts from the first
day it ran: no free source has past order books.

`make market-reports` (`market_reports.py`, ADR-096) turns the latest landed
reports into `data/derived/market_reports.json` for Dashboard → India → Deals &
filings: 30 trading days of bulk and block deals (a block trade NSE repeats in
the bulk list counted once), net buyers and sellers, the F&O ban against the
day before, MTF funding against five sessions back, short selling and SLBM
lending, ten days of SAST and PIT filings, promoter pledges from the last two
quarters, and IPOs. It runs between the download and the upload, so it reads
local files. An empty API answer within three days of its date is not landed:
NSE answers a day it has not published yet with an empty 200.

All three upload with `make upload-verified`, which deletes a local file only
when B2 holds it at the same size and the SHA-256 recorded at upload equals
the hash of the local bytes, computed again. A file that fails either check is
kept and named.

### Crypto minutes: month files and day files

Binance publishes one file per symbol per month, a few days after the month
ends, and one per day, the day after it ends. `crypto_backfill` lands months;
`crypto_fill` lands days from the first of the *previous* month to yesterday
(`crypto.fill_window`), so a month's last days arrive before its month file
does. A day already landed, on disk or in B2, or inside a landed month file, is
not asked for again. Both shapes stay in `data/landing/crypto/<SYMBOL>/`
because landing is immutable, and every reader drops a day file whose month
file is landed (`crypto.without_superseded`): reading both counted each minute
twice. The daily reader keeps each file's daily bars in
`data/cache/crypto_daily.json`, a derived file; a pruned month is downloaded
once, eight at a time, and its minutes are not kept on disk.

## 3.2 The bitemporal model: two clocks, not one

This is the most important data concept in the system, and the one most
commonly got wrong elsewhere.

Every stored record carries **two timestamps**:

| field | meaning |
|---|---|
| `event_time` | when the thing *happened* in the world |
| `knowledge_time` | when *we could first have known* it |

A third, `receipt_time`, records when we actually downloaded it.

**Why two clocks matter.** Suppose a company announces on 15 March that a
dividend went ex on 1 March. The `event_time` is 1 March. The
`knowledge_time` is 15 March. A backtest standing on 5 March **must not see
it**, because nobody could have. Using `event_time` alone would leak the future
into the past — an error that silently inflates returns.

The read API enforces this:

> **query(as_of) returns exactly those records where `knowledge_time ≤ as_of`.**

`as_of` is a **required, keyword-only** argument. You cannot forget it, because
the function will not run without it. This is what "structural, not
conventional" means in practice (ADR-014).

**A real mistake this caught.** An early version used the file's download time
as `knowledge_time`. The median gap between the real announcement and our
download was **1,820 days** — five years. Every backtest built on it was
silently reading the future.

## 3.3 The security master: what is an instrument?

Symbols are not identity. Companies rename (`ZOMATO` → `ETERNAL`), merge,
demerge and delist. If a backtest joins data on a ticker, it will silently
combine two different companies' histories.

So the system assigns an **internal instrument ID** and joins on it, never on a
ticker or a broker token. Instrument attributes are **time-versioned**: asking
"what was NIFTY's lot size on this date?" returns the value that was true then.

Measured from our own data, NIFTY's lot size was **50** (from 2024-03), **25**
(2024-11), **75** (2025-03), **65** (2026-03). Hardcoding any one of those
would corrupt every derivative calculation outside its window.

**A real mistake this caught.** Joining corporate actions on a raw ISIN string
lost **21.9%** of matches. Joining on the internal ID recovered them, which
changed adjustment-factor coverage from 78.1% to 98.1% and recovered 3,073
dividend factors that had been silently dropped.

## 3.4 Corporate actions: the mathematics of adjustment

When a company splits its stock 1-for-1, the price halves overnight. A holder
loses nothing — they now own twice as many shares — but a naive price series
shows a **−50% crash**.

### Price adjustment

For each corporate action we compute an **adjustment factor** `f`. For a bonus
or split where each old share becomes `r` new shares:

```
    f = r
```

A 1:1 bonus gives `f = 2.0`. To make historical prices comparable with today's,
every price **before** the ex-date is divided by the cumulative product of all
factors that occur **after** it:

```
    P_adjusted(t) = P_raw(t) / ∏ f_i     for all events i with ex_date_i > t
```

Verified against real data: **40 of 40** genuine 1:1 bonuses show the expected
~2× raw price drop, which the factor of 2.0 exactly corrects.

### Dividends and total return

A dividend `D` paid on a stock trading at `P` also drops the price. For
**total-return** series (which assume dividends are reinvested), the factor is:

```
    f_dividend = P_cum / (P_cum − D)
```

where `P_cum` is the last price at which the stock traded *with* the dividend
attached ("cum-dividend").

### Rights issues

A rights issue lets holders buy new shares at a discount, which dilutes the
price. The correct divisor is the **Theoretical Ex-Rights Price (TERP)**:

```
                N · P_cum  +  M · S
    TERP  =  ─────────────────────────
                     N + M

    f_rights = P_cum / TERP
```

where `N` = existing shares, `M` = new shares offered, `S` = subscription
price. This was cross-checked algebraically against the standard formula and
validated against Reliance's 2020 rights issue.

### The subtlety: two different adjusted series

The system uses **two** adjusted price series, and conflating them causes a
severe bug:

- **For signals** — prices adjusted *as of the decision date*, using only
  actions knowable then. A strategy deciding on 2018-01-15 must not see a bonus
  that goes ex in May.
- **For marking positions** — prices adjusted uniformly as of the *end* of the
  run, so a position's value does not jump on the day an adjustment updates.

**A real mistake this caught.** Marking positions from the raw series booked an
**89% phantom loss** on VIVIDHA (1,290.55 → 140.75 across an 11:1 action) and
dragged an eleven-year buy-and-hold result to −3.3%. The holder had lost
nothing.

## 3.5 Data quality: why the median, not the mean

To detect a corrupt price, you need a measure of "normal spread". The obvious
choice — standard deviation — is a trap, because **the corrupt values
themselves inflate it**, hiding the very thing you are looking for.

The technical term is **breakdown point**: the fraction of data that can be
arbitrarily wrong before the statistic becomes meaningless. Standard deviation
and the mean have a breakdown point of **0** — a single bad value can move them
without limit.

So the system uses **Median Absolute Deviation (MAD)**, breakdown point 0.5:

```
    MAD  =  median( | x_i − median(x) | )
```

To make it readable on a familiar scale, it is multiplied by 1.4826 (which is
`1/Φ⁻¹(0.75)`), so that for genuinely normal data it matches the standard
deviation:

```
                   x_i − median(x)
    robust_z  =  ────────────────────
                  1.4826 · MAD
```

A point is flagged when `|robust_z| > 3.5`. The scaling only affects how the
number *reads* — never which points are flagged relative to each other.

The same principle appears elsewhere: **Theil–Sen** regression instead of
ordinary least squares (breakdown point 0.29 vs 0), and **Spearman** rank
correlation instead of Pearson.

---

# Part II — Research

## 4.1 Features and the Information Coefficient

A **feature** is a number computed per stock per day that you hope predicts
future returns — for example, "12-month return, skipping the last month"
(`momentum_12_1`). The library has ten, each oriented so **higher is better**.

To ask whether a feature predicts anything, compute the **Information
Coefficient (IC)**: on each date, the rank correlation between the feature and
the return that followed.

```
    IC_t  =  Spearman( f_{i,t} ,  r_{i,t→t+h} )
```

where `f_{i,t}` is the feature for stock `i` on date `t`, and `r` is the return
over the next `h` days (default 21). Spearman = Pearson correlation *of the
ranks*, which is insensitive to outliers and to any monotonic rescaling.

You then get a time series of ICs, one per date. Its significance:

```
                mean(IC)
    t  =  ──────────────────────
           std(IC) / √T
```

with `T` the number of dates. A typical genuine equity signal has a mean IC
around **0.02–0.05** — small, and that is normal. What matters is consistency.

> **Warning attached to this project's own IC figures:** the Sprint 8 IC
> numbers were computed on *raw, unadjusted* prices over a 3-year panel and
> have not been recomputed (ticket T-1317). They should not be relied on.

## 4.1a The formula language (ADR-097)

A feature can also be written as a formula, so the research agent can compose
new ones without writing Python. `features/formula.py` parses the text into a
tree and interprets it; nothing is ever passed to `exec`.

```
    low_volatility     =  neg(ts_mad(ret(1), 62))
    price_to_52w_high  =  div(close, ts_max(close, 252))
    momentum_12_1      =  delay(ret(231), 21)
```

- **Inputs:** `close`, `volume`, `turnover` for one stock. Zero or negative reads as missing.
- **Operators:** `ret`, `delay`, `delta`, `neg`, `abs`, `log`, `sign`, `add`, `sub`, `mul`, `div`,
  and window operators `ts_mean`, `ts_std`, `ts_sum`, `ts_min`, `ts_max`, `ts_median`, `ts_mad`,
  `ts_rank`, `ts_drawdown`. Every one looks back only.
- **Limits:** depth 6, 24 operators, windows 1 to 504 sessions.
- **Missing data:** a window needs at least half its values. Division by zero and the log of a
  non-positive number are missing, not errors.
- **Lookback** is computed from the tree: `ts_op(x, n)` needs `lookback(x) + n − 1` rows,
  `delay(x, n)` needs `lookback(x) + n`, `ret(n)` needs `n + 1`.

A formula compiles into the same `Feature` as the library, so the IC screen, `RankAndHold`,
codegen, the critic and the idea lab's trial path take `feature: "formula:<text>"` on a card
through one resolver, `formula.resolve`. Every evaluation still spends a trial as before.

**The alpha zoo** is the ten library features rewritten as formulas. On full histories each
gives exactly the library's value (tested every 7 rows over 400). They can differ only when
most of a window is missing, because the hand-written features have their own minimum counts.

**Originality** is the size of the largest subtree a candidate shares exactly with another
formula, over the candidate's size. Wrapping a zoo formula in one more operator scores 0.75;
an unrelated formula that shares only `volume` scores 1/3. Research 131 plans to use it to
refuse ideas that copy the zoo or the graveyard.

**What it cannot do:** compare stocks with each other inside a formula (ranking stays in the
strategy), or read fundamentals, delivery or participant data. Each needs a new, tested input.

## 4.2 The cost model: itemised, not blended

Trading costs in India are not one number. They are a stack of separate
charges, each with different rules about which side pays. Blending them into
"0.1% round trip" is wrong in both directions.

For a trade of `Q` shares at price `P`, turnover `T = P × Q`:

| charge | rate (equity delivery) | falls on |
|---|---|---|
| Brokerage | 0 (delivery); min(0.03%, ₹20) otherwise | both |
| **STT** (Securities Transaction Tax) | 0.1% of turnover; an ETF unit 0.001% (A-047) | both, on delivery; an ETF unit on the sale only |
| Stamp duty | 0.015% | **buy only** |
| Exchange transaction charge | ~0.00325% | both |
| SEBI turnover fee | 0.0001% | both |
| **GST** | 18% | on *brokerage + exchange charges only* |

So:

```
    GST  =  0.18 × (brokerage + exchange_charges)
```

— **not** on turnover, and **not** on STT. Getting this wrong is a common error.

Two properties of the implementation matter:

1. **Rates are time-versioned.** STT on futures changed **4×** inside the
   backtest window. A hardcoded rate would misprice years of history.
2. **Everything is `Decimal`, not float.** Contract notes reconcile to the
   paisa, and a float that is out by 1e-9 fails that comparison for reasons
   unrelated to correctness.

> **Unverified:** every rate comes from a *secondary* source and has never been
> checked against a real contract note (T-906, A-016). This is the cheapest
> outstanding verification in the project.

### Four venues, one router

The table above is NSE. It stopped being the whole story when crypto, US equity
and FX arrived, and the way it stopped is the most instructive bug this
codebase has produced.

| venue | charge | round trip |
|---|---|---|
| NSE (`equity`) | the stack above; Zerodha brokerage capped at ₹20 | ~0.04% |
| US (`us`) | INDmoney 0.25% a leg **capped at $25**, plus 18% GST | ~0.012% |
| Crypto (`crypto`) | Delta 0.05% taker plus 18% GST | 0.118% |
| FX (`fx`) | the measured bid-ask spread, carried per bar | varies |
| Mutual funds | nothing modelled — gross, and labelled so | — |

Two things in that table are counter-intuitive and both were wrong here first.

**US is the cheapest venue, and only because of the cap.** Uncapped, 0.25% a leg
is 0.5% a round trip and no intraday signal in the library survives it —
friction on `orb_breakout` reached 309% of its gross edge. Capped, a $500,000
position pays $25 instead of $1,250, and the same round trip is 0.012%. A fee
model missing its cap is not conservative; it is wrong, here by a factor of
fifty.

**Which venue a trade pays is a required argument, everywhere.** It defaulted to
`"equity"`, and that default billed crypto Indian STT, then billed US trades
Indian STT, then — after both were fixed at the leaf — billed every *winning*
exit Indian STT, because two of six call sites had quietly kept it. Each wrong
number was plausible: an Indian bill on a US trade is about ten basis points,
which reads as a cost rather than as a bug.

`costs/router.py` is now the single answer to "what does this fill cost". There
were three, in different files, with different coverage: the intraday engine
knew crypto and NSE-intraday, the daily engine knew NSE-*delivery* and no crypto
at all, and a third place decided separately whether to charge anything. See
ADR-045.

**Spread and slippage are modelled on none of them** (A-030). That omission is
consistent across venues, so the four stay comparable to each other — and every
net figure this platform reports is better than a real fill would be.

## 4.3 Two backtest engines, and why

| | **Tier A** (vectorised) | **Tier B** (event-driven) |
|---|---|---|
| Speed | seconds | minutes |
| Models | decide/trade/own as one step | separate order → fill → position |
| Can express | position changes | rejections, partial fills, order IDs |
| Purpose | **screening only** | the real answer |

Tier A is explicitly **not a backtest** (ADR-021) — it is a screen. It cannot
model an order that was rejected because the stock did not trade that day.

Both engines run the **same `Strategy` object, unchanged**. This is a hard rule:
one interface used by Tier A, Tier B, paper trading and live. When the two
engines are configured identically they agree to **1.4 × 10⁻¹⁶ relative** —
machine epsilon.

**Rules both engines apply the same way (HISTORY #28).** A holding with no
panel row on or after the fill day has left the data (delisted, or merged into
another ISIN) and is sold at its last price before the day's rebalance. A
renamed stock is not in that set: the panel carries every ISIN under its
current symbol (`panel.canonical_symbols`). At a rebalance the orders go in
symbol order, all sells first. A buy is cut to what the cash on hand can pay
for, with `BUY_COST_RESERVE` (0.3%) held back for charges, and is skipped if
that is nothing. So cash never goes below zero, and no leverage appears that
the strategy did not ask for.

**Long only (2026-11-01, T-4363, ADR-115).** Both engines and the paper runner drop a
negative weight before normalising (`strategy.long_only`) and count it on the
result as `refused_shorts`. An Indian delivery position cannot be held short
overnight, and Tier B's cash accounting would book a short sale's proceeds as
profit. The longs are not scaled up to fill the gap: the book holds exactly
what it would with the shorts left out.

### The Strategy interface

A strategy is deliberately tiny:

```python
def target_weights(self, view: MarketView) -> dict[str, float]:
    ...
```

It receives what it may see and returns what it wants to **hold** — target
weights, not orders. It does not fetch data (so it cannot reach past `as_of`),
does not place orders (so the same object works in backtest and live), and does
not compute costs (so there is exactly one cost path in the system).

**Sizing is declared, not coded (ADR-122).** A strategy says what to hold,
best first; `Strategy.sizing` says how the money is split, and
`backtest.strategy.decide` applies it in Tier A, Tier B and the paper/live
runner alike. `equal`, the default, splits the strategy's gross exposure
equally, so a slot strategy that fills 4 of 10 slots stays 40% invested.
`strategy` keeps the weights as returned (Clenow's inverse ATR,
betting-against-beta, Faber TAA, the Nifty volatility target, sandbox code).
The models (`deploy/sizing_models.py`) use 126 days of daily returns:

- `inverse_vol`: weight proportional to 1/σ.
- `hrp`: López de Prado's hierarchical risk parity. Single-linkage clusters on
  the distance √(½(1 − ρ)), then a top-down split between halves in
  proportion to 1 − V_left/(V_left + V_right).
- `min_variance`: minimise wᵀΣw with 0 ≤ w ≤ max_weight(k) and Σw = 1, by
  projected gradient.

HRP and min-variance use Σ shrunk toward constant correlation,
Σ̂ = δF + (1 − δ)S, with δ from Ledoit & Wolf (2004). A model's weights are
capped at `max_weight(k)` before they leave `size_book`, and they fall back to
equal when fewer than 60 common return days exist.

## 4.4 The engine self-tests — the most important gate

Before trusting any strategy result, you must trust the engine. `make
test-engine` runs ten checks on synthetic worlds where the right answer is
known in advance:

- **Accounting invariants** hold after every single event.
- **Zero alpha = exact cost drag.** A strategy with no edge must lose *exactly*
  the modelled costs. It loses ₹78,113.65 over 365 fills, matching to the paisa.
- **Known alpha is recovered.** A planted 67.78% edge is recovered as 67.41%.
- **Absent alpha is not invented.** A no-edge strategy earns nothing.
- **Determinism.** Repeat runs are byte-identical.
- **Golden file.** Output matches a committed reference exactly.

There is also a **mutation suite**: deliberate bugs are injected to confirm the
tests actually catch them. This found a real hole — the zero-alpha identity
does *not* catch double-charged costs, because both sides of the identity
double. An independent recomputation was added to catch it.

### Where a backtest result is stored

Two layers per workspace. `results/<strategy>.jsonl` holds one small row per
run: the headline numbers, a 64-point curve and the configuration hash
(`results.py`). `reports/<strategy>/` holds the full report: every fill,
per-instrument attribution, the daily equity curve, closed trades and the
parameters.

Every run gets an id (`<UTC time>-<payload digest>`) and its own file,
`reports/<strategy>/runs/<configuration>/<run_id>.json`, written once and
never replaced. `reports/<strategy>/<configuration>.json` is a copy of the
latest run, so a re-run updates what the library shows without destroying
what it showed before. Each report's `provenance` names the git commit, the
uncommitted paths and the cost-model stamp. `/api/report?run=<id>` opens an
earlier run; the response's `history` lists them.

Closed trades (`trades.py`) are matched first in, first out per symbol, one
trade per closing fill, the same rule as the report page. MAE and MFE are the
worst and best unrealised P&L between entry and exit, read from the adjusted
closes the engine marked at, so they miss intraday extremes. The intraday paths
pass no closes, and their MAE/MFE is `None`.

---

# Part III — Validation: catching self-deception

## 5.1 Cross-validation that does not leak

Standard k-fold cross-validation is **invalid for time series**. Two reasons:

1. **Lookahead.** Training on 2020 to predict 2018 is meaningless.
2. **Leakage through overlapping labels.** If your label is a 21-day forward
   return, then a training sample from day 100 and a test sample from day 110
   share 11 days of the *same future*. They are not independent.

The fix is **Combinatorial Purged Cross-Validation (CPCV)**:

- Split time into `n` contiguous **blocks** (default 6).
- Choose every combination of `k` blocks as the test set (default 2), giving
  `C(6,2) = 15` distinct paths.
- **Purge**: remove training samples whose label window overlaps the test
  period — that is, drop the `horizon` days immediately adjacent.
- **Embargo**: additionally drop a further `embargo` days (default 5) *after*
  each test block, because serial correlation leaks slightly past the label
  window.

Multiple paths matter: a single train/test split gives one number, and one
number cannot tell you whether your selection process is picking noise.

**A real mistake this caught.** The first leakage check condemned 14 of 15
*correct* paths — it was measuring gaps against the real calendar rather than
against the filtered timeline of days actually present.

## 5.2 Sharpe ratio and its moments

The **Sharpe ratio** is return per unit of volatility, annualised:

```
              mean(r)
    SR  =  ──────────── × √252
              std(r)
```

with `r` the daily returns and 252 trading days per year.

No risk-free rate is subtracted: `r` is the raw daily return, not the return in
excess of cash as Sharpe (1994) defines it. This flatters any strategy that is
mostly invested, by about 0.4 of Sharpe at 15% volatility with cash at 6%
(A-083, T-4249).

The system also computes **skewness** and **excess kurtosis**:

```
    skew  =  (1/n) Σ (r_i − r̄)³ / σ³

    kurt  =  (1/n) Σ (r_i − r̄)⁴ / σ⁴  −  3
```

These are not decoration. Most trading strategies have **negative skew** (many
small gains, occasional large losses) and **fat tails**, and the correction in
§5.3 is *larger* for such streams. Ignoring them understates the correction in
the flattering direction.

> One configuration in this project still shows excess kurtosis ≈ **155**
> (T-1310). Fat tails there are not fully explained.

## 5.3 The Deflated Sharpe Ratio — the heart of the matter

Return to §1. If you try `N` strategies, what Sharpe should the *best* worthless
one show? Bailey & López de Prado's approximation to the expected maximum of
`N` independent standard normals:

```
    SR₀  =  σ_SR · [ (1 − γ)·Φ⁻¹(1 − 1/N)  +  γ·Φ⁻¹(1 − 1/(N·e)) ]
```

where `γ ≈ 0.5772` (the Euler–Mascheroni constant), `Φ⁻¹` is the inverse normal
CDF, and `σ_SR` is the standard deviation of Sharpes across trials.

**This is the bar to beat.** It rises with every strategy you try.

> **σ_SR is assumed, not measured, and it scales the whole bar (A-021).** The
> implementation defaults it to 1.0 and nothing has ever overridden it. The
> same 19 trials give a bar of **0.94** at σ_SR = 0.5, **1.88** at 1.0, and
> **2.82** at 1.5 — a range that spans this project's best-ever result of 1.27.
> So the sentence "the gate has killed everything it has seen" rests on this
> constant as much as on the evidence.
>
> `ledger.sharpe_dispersion()` measures it from the trial ledger and, at the
> time of writing, **refuses**: only 3 entries carry a Sharpe and all three are
> H-0001 at successive stages. Dispersion is taken across *distinct subjects*,
> never across entries — one hypothesis re-evaluated eight times is one
> strategy, and counting the repeats would report our own re-measurement noise
> as the spread between ideas, shrinking σ_SR and lowering the bar. `ic` trials
> have no Sharpe at all, since they measure rank correlation, so they can never
> contribute. The API reports `noise_bar_sigma_measured: false` and the
> workbench marks the bar **assumed** until five distinct subjects exist.

The **Deflated Sharpe Ratio** then gives the probability that the true Sharpe
is above zero, given that `N` attempts were made:

```
                   ( SR − SR₀ ) · √(n − 1)
    DSR  =  Φ  ────────────────────────────────────
             √( 1 − skew·SR + ((kurt + 2)/4)·SR² )
```

where `n` is the number of return observations and `SR`, `skew`, `kurt` are in
**per-period** units, and `kurt` is **excess** kurtosis (0 for a normal). The
paper writes `(γ₄ − 1)/4` with raw kurtosis `γ₄ = kurt + 3`.

Read it as a probability: **DSR = 0.95** means a 95% chance this is not noise.
The mandate requires ≥ 0.95.

Note the denominator. Negative skew makes `−skew·SR` positive, **enlarging** the
denominator and **shrinking** DSR. Fat tails do the same. A strategy with ugly
moments is penalised, correctly.

> **Replaced on 2026-10-31 (ADR-108): see 5.3a.** Under the old rule, 19
> ledger rows and σ_SR = 1.0, the noise bar was **Sharpe 1.88**. The best result this project has ever produced is
> **1.27**. Read that again: the best strategy found so far is *below* what
> pure noise would be expected to produce given how much has been searched.

## 5.2b Validating an intraday rule (ADR-139)

`make validate H=...` re-runs a daily `rank_and_hold` strategy on each path.
For an intraday rule registered in `validation/intraday.py` (`SOURCES`: H-0052,
H-0065, H-0096, H-0098) it scores the battery from the rule's own trades instead: daily net
return on the rule's capital for every session (zero on a day without a
trade), CPCV paths over those sessions with a one-session purge, the same
deflated Sharpe, search bar and Romano-Wolf test, and the stresses the gate
reads recomputed from the trades (costs x2 and x3, the five best names
removed, each half of the sessions, entry five minutes late). With one
configuration the probability of overfitting has nothing to choose between
and is 0 over 0 paths.

From 2026-11-07 (ADR-145, ADR-146) the battery reads any trade through the
`DayTrade` protocol (symbol, day, gross, costs), so `SOURCES` also holds
index-option straddles (`options/index_expiry_screen.py`, H-0041, H-0103 to
H-0105), index-futures rules on index minutes (`intraday/index_futures_screen.py`,
H-0099 to H-0102), the F&O ban exit (H-0106) and the MFT stock scalps
(`intraday/mft_screen.py`, H-0111 to H-0130; `intraday/quant_screen.py`, H-0131 to H-0140, five long and five short chosen at 09:20; `intraday/onex_screen.py`, H-0141 to H-0150 at 1x, ₹1 lakh a position, with NSE filings as news; `intraday/other_data_screen.py`, H-0151 to H-0160, whose swing rules are delivery holds marked to market each session as `Piece`s so a day's P&L lands on that day; `intraday/daily_universe_screen.py`, H-0161 and H-0162 on daily bars of the 500 most traded NSE stocks each day, free of today's F&O list; `intraday/daily_more_screen.py`, H-0164 to H-0173 in the same frame; `intraday/new_signals_screen.py`, H-0184 to H-0193, with price-limit closes, India VIX, institutional bulk-deal clients and multi-day delivery). H-0187's paper book is `daily_books.h0187`. H-0161's paper book (`deploy/delivery_fade_book.py`, ADR-148) reads daily bars after the holdout end and skips stocks on the previous evening's ASM/GSM snapshot (`nse_reports` `asm`, `gsm`) or in series BE/BZ (`ingest/trade_for_trade`). H-0168's and H-0162's books (`deploy/daily_books.py`, ADR-149) read results announcements landed one finished day at a time and SAST after the holdout end; a 20-session hold is booked on its exit day with `segment: delivery`, which `study_book.replay` charges at delivery rates. `research/library_reports.py` stores each gated card's research-window run and report in the result store, so the library and Report page show it. The scalps decide on the
5-minute closes of research 161's snapshots, fill at the next minute's open,
trade ₹5 lakh (₹1 lakh of margin at 5x MIS), at most ten open, and return on
₹10 lakh of margin; their late-entry stress fills five minutes after the
decision. Their paper books (`deploy/mis_book.py`, ADR-147) call the same rule functions on snapshots built from minute files after the holdout end, a position at half the deployment's capital in notional. For a one-underlying straddle, "drop best 5 names" removes
everything and reads 0% kept.

## 5.2c The rule engine and the research autopilot (ADR-150)

Research 166-176 needed a new screen module for every batch, so only a person
could test an idea. `intraday/rule_engine.py` makes a daily-bar event rule data.
A card's `engine:` block is:

    kind: intraday | swing      hold: 0 | 2-60 sessions
    side: long | short | against | with   (+ direction_of: a signal whose sign sets the side)
    when: 1-5 conditions, all must hold   (signal, lag, n, absolute, op, value)
    rank_by: a signal, desc | asc         (ten a day, or ten open, best first)

The signals are `gap`, `ret(n)`, `day_return`, `delivery_ratio`, `value_ratio`,
`at_high(n)`, `at_low(n)`, `results_morning`, `bulk_buy`, `bulk_sell` and
`promoter_buy`. `lag` counts sessions before the entry session, and entry is
at its official open. A signal that reads a close needs `lag >= 1`, so a rule
that looks ahead does not parse. The window starts on the first day every
signal's data exists (2016-01-01, or 2021-07-01 for deals and results) and
ends at `DATA_END`. The card cannot choose it. The universe, costs, sizing
and books are research 173's (`daily_more_screen.day_book`/`swing_book`).
Research 176's ten rules, written as specs (`REFERENCE`), reproduce its
published counts and Sharpes exactly (`make rule-engine-check`).

Every screen adds five checks. A rule is gated only if it passes the screen
(net positive in both halves and at 2x costs) and none of these flags:
fewer than 100 trades; under half the Sharpe kept without the five best
stocks; positive in under 60% of years; the best 1% of sessions making over
half the profit. Sharpe at 3x costs is shown for information.

`validation/intraday.source(h)` falls back to the engine for a card with an
`engine:` block, so `make validate`, `make gate`, `library_reports` and
`rule_book` (through `deploy/engine_book.py`, which reads data after the holdout
end only) take an engine card with no new code.

**The nightly loop** (`make agents-autopilot`, part of `make agents-ideas`):

    autopilot agent writes ~10 specs (Claude Sonnet -> Groq -> fixed rules), half intraday
      -> parse; drop repeats by fingerprint (every engine card and research 176's ten)
      -> hypotheses/H-NNNN.yaml, committed alone: the pre-registration
      -> one screen pass (no trial) -> bias checks
      -> "a new bet": daily returns correlating 0.5 or more with any pass (H-0161,
         H-0162, H-0168, the autopilot's own) or a better rule that night -> not gated
      -> clean survivors, and older ones waiting: validate + gate while the week's
         allowance of ledger entries lasts (gate_entries_per_week, 10)
      -> PROMOTE or PAPER: library report + paper deployment
      -> result line on each card, docs/RESEARCH/NNN-autopilot-<day>.md, one commit,
         an inbox item and a Telegram line

The agent itself only writes cards (`agents/workers/autopilot.py`). The rest is
`research/autopilot.py`, run as that agent's run (`runtime.run(worker=...)`), so
the boundary that keeps agents away from the gate still holds for every module
in `agents/`.

## 5.3a The bar from what was searched (ADR-108, research 138)

From 2026-10-31, by operator decision, `N` and `σ_SR` in 5.3 come from the
search itself, not from the ledger's row count and an assumed 1.0.
`validation/search_bar.py`, called by `make validate`:

1. **Families.** Every stored India equity strategy (one configuration each,
   as in 5.9) plus the hypothesis's own configurations is clustered by
   average linkage at correlation 0.7. `N` = families; `σ_SR` = the spread of
   the families' annualised Sharpes, each family equal-weighted inside. The
   deflated Sharpe and the minimum backtest length both use these. A tenth
   variant of one idea joins its family and moves nothing; a new kind of idea
   adds one family. First reading: 27 families, σ 0.48, bar **0.98**.
2. **Romano-Wolf StepM.** The best configuration's daily return over Nifty
   (beta 1) is tested jointly with every stored strategy that traded on at
   least 90% of its days, on their common window. Statistic: √T · mean / sd.
   A stationary block bootstrap (mean block 20 days, 2,000 draws, fixed
   seed) of all columns together gives the distribution of the maximum
   statistic; its 95th percentile is the critical value, stepped down until
   nothing more is rejected. The candidate passes only if it is rejected as
   no-edge. No `N` or `σ` is assumed: correlation between strategies is in
   the bootstrap. First reading: critical Sharpe 0.95 over Nifty on
   2016-01-25 to 2026-09-30.

**Every screen shows this bar (2026-11-01, HISTORY #50).** The library's
"Beats the bar", the dashboard count, backtest caveats, deploy preflight and
`/api/health` all use `search_bar.shown_bar`: the family bar over the stored
reports, recomputed when a report is added or rewritten. Only with fewer than
two stored reports does it fall back to the ledger-count bar, and its note
says so. The backtest dialog's "bar if recorded" is now an upper bound: every
new configuration counted as a new family.

The pack records both under `search`; `gates.py` kills a pack whose
`search.method` is not the mandate's, or whose Romano-Wolf test is missing,
failed, or run at a looser level than `mandate.yaml` sets. The ledger still
records every trial; it no longer sets the bar.

**What it cannot see.** Runs that store no daily returns: optimiser and
walk-forward sweeps (T-4301). A tuned strategy's own search is therefore
invisible, which is why `india_sharpe_momentum_opt`'s pass is not evidence
yet (T-4302). Families use equal weights and average linkage, not the paper's
minimum-variance weights and ONC (S-057). The gate-acceptance packs carry no
`search` block, so they now also die on it; they were already dying on DSR,
PBO and worst regime.

## 5.4 Probability of Backtest Overfitting (PBO)

DSR judges one strategy. PBO judges **the act of choosing**.

For each CPCV split:

1. Find the configuration that scored best **in sample**.
2. Look up where that same configuration ranks **out of sample**.
3. Convert its relative rank `ω ∈ (0,1)` to a logit:

```
    λ  =  log( ω / (1 − ω) )
```

Then:

```
    PBO  =  fraction of splits where λ ≤ 0
```

i.e. how often the in-sample winner lands **below the out-of-sample median**.

- `PBO > 0.5` — worse than a coin flip; your selection is picking noise.
- `PBO > 0.25` — substantial overfitting risk.
- Mandate allows ≤ **0.25**.

This indicts the *procedure*, not any single configuration. That distinction is
the whole point.

## 5.5 Minimum Backtest Length

The blunt version of the same idea. How many years of history do you need
before a Sharpe of `SR_target` is distinguishable from luck, given `N` trials?

```
    MinBTL  =  ( SR₀ / SR_target )²      years
```

If the answer exceeds the history you actually have, **no amount of analysis on
that history can support the claim.** The mandate requires at least 1.5× the
needed length.

## 5.6 Stress tests: when does it break?

The rest of the battery asks "could this be luck?". Stress asks "what has to
stay true?".

| test | question | mandate |
|---|---|---|
| **2× costs** | Does the edge survive doubling every charge? | ≥ 60% of Sharpe retained |
| **Drop best 5 names** | Is it a handful of lucky positions? | ≥ 60% retained |
| **Worst regime** | Does it work in more than one market? | ≥ 50% retained |
| **Signal staleness** | Does a delay destroy it? | must stay positive |

**A real mistake this caught.** The cost-stress test originally scaled only
*brokerage* — which is **zero** on delivery trades. So "2× costs" quietly meant
"introduce a 0.06% fee that did not exist", while STT and stamp duty (the
charges that actually dominate) were untouched. It reported 95% of Sharpe
surviving 5× costs, which was not a fact about the strategy. The multiplier now
applies to the total of every charge.

## 5.6a Monte Carlo resampling: order versus luck

Two questions the rest of the battery does not ask, and they need **different**
operations (ADR-034):

**Shuffle** — reorder the same returns. Mean and standard deviation are
unchanged, so the Sharpe is *identical in every path*; reporting a distribution
of it would be reporting nothing. What changes is the equity path, because a
drawdown depends entirely on the order losses arrive in:

```
    max_drawdown  =  min over t of  ( E_t / max(E_1..E_t) − 1 )
```

If the realised drawdown is **shallower** than the median reshuffled path, the
backtest simply has not met its bad ordering yet.

**Bootstrap** — resample with replacement. This *does* move the mean and the
standard deviation, giving a genuine confidence interval on the edge.

> Measured on `momentum_12_1` over 700 days: observed Sharpe **0.11**, bootstrap
> 5th percentile **−0.96**. The data cannot rule out that there is no edge at
> all.

Both assume returns are **exchangeable**. Real returns cluster — a crash is a
run of bad days, not bad days sprinkled evenly — and shuffling breaks up
exactly the clustering that produces the worst drawdowns. So this is a **lower
bound** on risk, never the whole of it. Neither test spends a trial, because
resampling an existing result evaluates nothing new.

## 5.7 The trial ledger: a counter that cannot be quietly edited

Every strategy configuration evaluated appends one entry to
`data/derived/trial_ledger.jsonl`. Each entry contains the hash of the entry
before it — a **hash chain**:

```
    hash_i  =  SHA256( payload_i  ‖  hash_{i−1} )
```

Altering or removing any row breaks every link after it. This does not make
tampering impossible — anyone can rewrite the whole chain — but it makes it
**detectable and deliberate** rather than quiet.

**Why this file specifically?** Because every statistic in §5.3–5.5 gets *more
favourable* as the trial count falls. DSR rises. MinBTL shrinks. The
multiple-testing correction weakens. The one number the entire battery rests on
is also the one with the strongest incentive to shrink, and "we promised not to
touch it" is not a control.

The validation battery **refuses to report anything** if the chain is broken.

> **A real incident, recorded.** On 2026-08-20, `make gate H=H-0001` was run
> merely to check the command still worked. It logged trial #19 — a second
> evaluation of an already-killed hypothesis. The bar moved from Sharpe 1.83 to
> 1.88, permanently, for every future candidate. There is no un-spend function
> and there should not be (ticket T-2609).

## 5.8 The promotion gate

`gates.py` and `mandate.yaml` are **operator-owned**. The AI that built this
system may propose changes in a review; it may not edit them without the
operator's instruction in that session (given 2026-11-06, ADR-140).

The separation is structural:

- **`mandate.yaml` holds every threshold and no logic.**
- **`gates.py` holds logic and no thresholds.** A test enforces that no numeric
  literal appears in it.

So a threshold cannot be relaxed as a side effect of a refactor. Changing what
the gate demands means editing a YAML file the operator owns, visibly, on its
own.

Three more properties:

1. **The default answer is no.** A check that cannot be evaluated *fails*. A
   missing field fails. Wrongly killing a good strategy costs an opportunity;
   wrongly promoting a bad one costs money.
2. **The verdict is one word.** PROMOTE, PAPER (ADR-141) or KILL. There is no "pass with
   concerns", because a gate that can express reservations will be overruled by
   whoever reads them.
3. **A strategy the gate kills is dead.** It is not tuned and resubmitted.
   Resubmitting under a new ID is visible in the ledger, which is what the
   ledger is for.

**The holdout** is a slice of data read **exactly once**, by the operator's
action, only after a PROMOTE. There is no un-spend function. A KILL verdict
refuses the read entirely.

**Two modes (ADR-140).** `mandate.yaml` `mode:` picks the bar. Since
2026-11-06, on the operator's instruction, it is `simple`: full-sample net
Sharpe above zero, each half of the history net positive, still positive at
2x costs, probabilistic Sharpe ratio at least 0.95 (the chance the true Sharpe
is above zero given the sample's length, skew and tails, without the
correction for how many things were tried), and net positive in at least 60%
of calendar years with 60 or more sessions. `strict` applies 5.3-5.3a and the stress retention thresholds
below, which are kept unchanged. The process rules (pre-registration, signed
evidence, intact ledger, one holdout read) apply in both.

**Three verdicts (ADR-141).** PROMOTE, PAPER, KILL. A strategy that misses
the promotion bar but has sound evidence (process rules pass) and clears
`paper:` in the mandate (net full-sample Sharpe above 0, probabilistic Sharpe
at least 0.80) gets PAPER: it may be paper-traded for forward evidence and
re-gated with it. A PAPER never reads the holdout and never reaches live: in
`forward.stage` it has its own stages, `paper_candidate` and
`paper_evaluation`, which the live preflight does not accept. Anything else is
KILL.

**Acceptance:** three deliberately overfit strategies are fed to the gate; all
three must die. They do under the strict bar — killed on deflated Sharpe, PBO
and worst-regime. `make gate-acceptance` checks the strict bar only, so it
does not test the simple bar now in use.

## 5.9 The strategy map: how many different bets do we hold? (ADR-106)

Every new strategy raises the noise bar (5.3). A book of several strategies
can clear a bar none of them clears alone, but only if they are different. For
K strategies of equal Sharpe s and average pairwise correlation ρ, an
equal-weight book has

```
    SR_book  =  s · √( K / (1 + (K − 1)·ρ) )
```

so ten rules at s = 0.9 make 0.99 at ρ = 0.8 and 2.06 at ρ = 0.1.
`research/strategy_map.py` (`make strategy-map`) measures ρ for what we hold.

- **Input:** the longest stored report (`reports/<strategy>/<configuration>.json`)
  of each India equity strategy with 500+ daily returns; `buy_and_hold` is left
  out as a benchmark. Nothing is re-run, so no trial is spent.
- **Correlation:** Pearson on daily returns, over the days both traded; fewer
  than 250 shared days is unknown, not guessed. Also computed after taking out
  NIFTYBEES at each strategy's full-sample beta (an upper bound, S-056).
- **Families:** average-linkage clustering; two groups join while their
  average correlation is at least 0.7. An unknown pair counts as 0.
- **Independent bets:** the participation ratio `(Σλ)² / Σλ²` of the
  correlation matrix's eigenvalues (negatives clipped): N for N unrelated
  strategies, 1 for N copies.
- **One fixed book:** equal weight across families, equal within, rebalanced
  daily. Fixed before any number was seen and marked `is_a_candidate: false`:
  its members have seen every window.

**First reading (2026-10-31, 68 strategies, HISTORY #44):** 27 families, 2.78
independent bets, average correlation 0.55. One family holds 39 strategies
(average correlation 0.79). With Nifty out: 45 families, 5.97 bets, and the
momentum and trend core is still one family of 17 at 0.80. The fixed book makes
Sharpe 0.60, and −0.28 hedged. Output: `data/derived/strategy_map.json`.

## 5.5 The optimisation pipeline, and what each stage costs

Four commands, each answering a different question. They are separate because
conflating any two of them loses the distinction that makes the answer readable.

| command | asks | trials |
|---|---|---|
| `make optimize` | which parameter setting is best, on the market the paper tested? | **one per candidate** |
| `make adopted-results` | what does the chosen setting actually do? | none |
| `make us-all` | does this signal work on US equity at all? | one per strategy |
| `make walk` | does the setting that won in sample survive out of it? | one per grid point |
| `make prune-runs` | (housekeeping) keep one stored run per strategy | none |
| `make evidence` | where does evidence live, and what is the bar charged for? | none |

**`optimize` sweeps on the market the paper tested**, from each signal's
`recommended_class`, not on whatever data is convenient. Nine of the coded
signals cite a study run on MNQ futures and were being swept on an Indian
large-cap; nothing errored and every number was plausible. The wrong market did
not produce an obviously wrong answer, it produced a **differently shaped** one —
`orb_breakout` showed an 8× best-to-median spread on RELIANCE and 1.3× on QQQ,
and the shape is the whole finding. See ADR-043.

**`adopted-results` spends nothing, and the reason is narrow.** A trial is a
configuration evaluated *in a search*. It re-runs only parameter sets a recorded
sweep already contains, on the same window, to extract another statistic — a
Sharpe — from trades the ledger has already paid for. If it ever gained the
ability to try a setting the ledger has not seen, it would be a search wearing a
different name and would have to pay like one.

**`walk` is the only out-of-sample evidence here.** The noise bar corrects for
*how much searching happened*, which is a real correction and a different thing
from testing on days the choice never saw. Sessions are cut into six blocks and
two held out at a time, in every combination — fifteen splits.

### Reading PBO requires a second number

A high PBO has two opposite causes and the ratio alone cannot tell them apart.

When **most settings are profitable** they perform near-identically, so which
one wins in sample is close to a coin toss and PBO climbs toward 0.5 *by
construction*. That says the parameter does not matter, not that the strategy is
fitted. When **few settings are profitable**, the same number means the search
is finding whichever ones happened to work on the training days.

```
    orb_breakout      PBO 0.47    9/9 settings profitable OOS    13/15 splits
    ou_reversion_in   PBO 0.07    5/16 settings profitable OOS    8/15 splits
```

Read naively the first looks worse. It is not. `optimize_walk.verdict` reports
the profitable share beside the ratio for this reason, and A-039 records it.

### The walk splits by session and does not purge

Splitting by session assumes a session's result does not depend on which other
sessions were in the training set. For a strategy flat at every close that is
nearly true and not exactly: with a 120-bar lookback on 375-bar sessions, the
first 120 bars of each session read into the previous one. `validation/cpcv.py`
purges exactly this for daily panels; the intraday analogue leaves it explicit
and undone, which makes every PBO here **mildly optimistic** (A-040).

---

# Part IV — Execution: from decision to order

## 6.1 The order state machine

The core insight: **a send has three outcomes, not two.** It landed, it did not
land, or *we do not know*.

```
      INTENT ──send ok──► SENT ──ack──► ACKNOWLEDGED
        │                  │                 │
        │                  ├──fill──────────►├──fill──► FILLED ●
        │                  ├──reject────────►├─reject─► REJECTED ●
        │  refused         │                 └─cancel─► CANCELLED ●
        ├──locally──► UNSENT ●               │
        │                  │                 │
        └──ambiguous──► UNKNOWN ◄────restart─┘
                           │
                           │  ONLY a broker query leaves here
                           ├── query found resting  ──► ACKNOWLEDGED
                           ├── query found filled   ──► FILLED ●
                           ├── query absent         ──► UNSENT ●
                           └── query FAILED         ──► UNKNOWN  (stays)

                                              ● = terminal
```

**`UNKNOWN` is a state, not an error.** A network timeout, a connection reset,
a process killed mid-send — all leave an order that may or may not exist at the
exchange. Systems that model two outcomes handle the third by guessing, and
guessing wrong costs money in **both** directions:

- Assume it failed → retry → **you are double-sent**.
- Assume it worked → **you are short a position you think you hold**.

So `QUERY_FAILED` maps `UNKNOWN` back to `UNKNOWN`. There is deliberately **no
timeout after which the system gives up**. A test asserts this over the entire
transition table, not over chosen examples.

**"Absent" needs a book that remembers.** Kite's `orders()` holds only today's
orders. An order sent on an earlier day and missing from today's book has not
been shown never to exist, so for an adapter with `order_book_is_daily` the OMS
does not resolve it as `UNSENT`: it stays `UNKNOWN` and is reported as a break
for a human with that day's trade book or contract note (T-4349).

**Duplicates.** The OMS never sends a client order id it has journaled. As a
second line, `KiteBroker.place` reads the day's order book first and refuses a
tag already there (unless rejected or cancelled), because Kite itself accepts
duplicate tags; `ems.send` reads that refusal as the original landing. If the
book cannot be read, nothing is sent (T-4348).

**Positions are the opening holding plus the net book.** Kite moves a
delivery stock out of `positions.net` into `holdings` the day after it is
bought, and shows a sale out of holdings as a negative CNC net row while also
lowering `holdings.quantity`. So `KiteBroker.positions` counts each holding's
`opening_quantity` (fixed for the day) plus the net book, which is right
whichever way the sale shows. A holding whose `quantity + t1_quantity
+ used_quantity` is not its `opening_quantity`, that has no opening quantity,
or that holds MTF shares raises rather than being guessed, as does a failed
read of either book (T-4364, RESEARCH/139, A-091, HISTORY #55).

**`UNSENT` ≠ `REJECTED`.** Both terminal, opposite meanings: `UNSENT` means the
exchange has no record; `REJECTED` means it saw the order and refused.

## 6.2 The write-ahead journal

**The intent is written to disk and `fsync`ed *before* the network call.**

Reverse those two lines and a crash in between leaves an order at the exchange
that no local record mentions — invisible to reconciliation forever, because
reconciliation compares against a list that does not contain it. That is the
one failure mode with no recovery path at all.

The journal is append-only JSONL with strictly increasing sequence numbers
(gaps reveal deletion). A **torn final line** — a crash mid-write — is dropped,
because that event never completed. A malformed line **anywhere else** raises,
because it cannot have come from a crash. A damaged journal must never read as
an empty one.

## 6.3 The rate governor

`max_orders_per_second` (default 5) is read from config, never hardcoded.

It is implemented as a **sliding one-second window**, not a token bucket. The
distinction is not academic: a bucket refilling 5 tokens per second permits 5
sends at 0.99s and 5 more at 1.01s — **ten orders inside 200 milliseconds**,
which is precisely the burst the rule exists to prevent.

The limit is per client at the exchange, not per process. `ems.live_governor()`
keeps the window in `data/oms/rate_window.json` behind an exclusive file lock,
with wall-clock times, so every live sender on the machine shares one window
(T-4350). Paper books keep a window each; their orders never reach an exchange.

## 6.4 Reconciliation: the broker is right

Local position state is a **cache**. The broker is the source of truth.

Taking that literally has one consequence people flinch at: **the fix is always
to the local record, never to the market.** The reconciler will rewrite what we
think we hold. It will *never* place an order to make the broker match our
belief, and there is no flag to enable it.

Why? A break means we do not know what happened, and the commonest cause is a
fill we failed to record. Trading the difference **doubles** the position
exactly when we are least able to tell.

Four break types, worst first:

| kind | meaning |
|---|---|
| `broker_only` | a position we have no record of — **unmanaged risk** |
| `quantity` | both know the symbol, sizes disagree |
| `local_only` | we think we hold it, the broker does not |
| `unknown_order` | an order working at the broker we never sent |

## 6.5 Kill switches

**Anything may trip it. Almost nothing may clear it.** Tripping is cheap and
reversible — the cost of a false trip is a day of not trading. Clearing re-arms
a system that something just decided was misbehaving.

- `trip()` is importable and needs no credential.
- There is **no reset function anywhere in the importable surface.** Clearing
  happens behind a CLI flag and requires `KILLSWITCH_TOKEN`, a variable the
  trading process never loads. A test asserts no other module in `src/` even
  *names* it.
- The **first** trip reason survives later trips — later ones are consequences
  of having already stopped.
- An unreadable trip file still reads as *tripped*. Failing to parse must never
  mean "clear".

Automatic limits: daily loss, orders per day, consecutive rejections, position
notional, and unresolved (`UNKNOWN`) orders.

> **Honest limitation (S-019).** On one machine with one user account, a
> process can delete the trip file directly. The separation is by code
> structure and credential, **not by the operating system**. Real separation
> means a different user on a different host, and a second broker API key whose
> only power is to square off and disable — so the switch works when *this
> machine* is the broken thing.

## 6.6 Chaos testing

`make chaos` runs eleven scenarios. Two of them **genuinely `SIGKILL` a real
subprocess** mid-order and then ask a fresh process to work out what happened
from the files on disk:

| scenario | the question |
|---|---|
| killed *before* the send | do we invent a position never placed? |
| killed *after* the send | do we lose a position that *was* placed? |
| ambiguous send | do we guess, or go and ask? |
| lost send | same event, opposite truth — do we tell them apart? |
| retry | does sending twice send twice? |
| broker down | does an unanswerable question get answered anyway? |
| rate limit | is the governor a real bound or an average? |
| kill switch | does tripped mean tripped? |
| out-of-band position | do we notice risk we did not create? |
| corrupt journal | does a damaged record read as an empty one? |

`SIGKILL` rather than an exception, because exceptions unwind: `finally` blocks
run, buffers flush. A power cut does none of that.

## 6.7 Paper trading and the reality gap

**There is no paper-trading loop.** There is the Tier B engine with a different
`Executor` plugged in — `OMSExecutor` instead of `SimulatedExecutor`. That is
the entire difference.

The consequence is strong: a **frictionless** paper run must reproduce the
backtest **exactly**. Measured on the real panel over 546 days and 829 trades,
the gap is **0.00**. If it were ever non-zero, the two paths have drifted, and
that is a defect to fix rather than a market fact to explain.

The reality gap decomposes into five terms:

```
    gap  =  slippage
         +  cost charged on a different price
         +  trades the backtest made and paper did not
         +  trades paper made and the backtest did not
         +  position divergence, marked to market
```

> **What the residual does and does not prove (S-018).** Both books are ours,
> so this decomposition is an **identity** and closes to zero by arithmetic. It
> proves the arithmetic, **not** that live execution is understood. The build
> plan's "residual under 10%" target concerns a *live* shortfall and cannot
> exist until there is a real counterparty.

## 6.8 Deployments: trading forward with the operator's capital

A deployment (`deploy/`) is one strategy, one capital amount, one start date,
and its own folder: OMS journal, paper broker, kill switch and last state.
`make paper-daily` brings each active one up to the latest close by
**replaying it from its start** through the Tier B engine with
`OMSExecutor` (ADR-060). In `make daily` it runs straight after the NSE
files and `build-panel`, before every slow or network-heavy step, and a failed
cloud sync no longer stops the run. `build-panel` reads a day still in local
landing from disk and goes to B2 only for days already pruned, so today's close
never waits on the mirror. Client order ids are deterministic and `OMS.submit`
returns a journalled order without re-sending it, so replayed days re-read
their fills and only new days send. Missed days are caught up in one run.

Timing is the backtest's: decide on day *t*'s close, fill at day *t+1*'s
price, here 5 bps worse (A-048), with Indian costs and 1% of equity kept in
cash for them. Money is marked at raw closes, so a replay cannot re-size a day
already traded; a split on a held name reads as a loss until S-038 is fixed.

**Capital fit.** Before sizing, `fit_to_capital` (ADR-120) ranks the
strategy's names (weight, then the strategy's own order; the strategy's order
alone when it sets `ranked_by_order`, as Clenow's does because its weights are
sizes). It then finds the largest *k* for which *k* names can each buy at least
one share at today's close: take the top *k*, cap every weight at
`max_weight(k)` and spread the excess over the rest in proportion, and if a
name still cannot buy a share, skip it and take the next-ranked name. The caps
are 100% for 1 name, 35% for 5, 25% for 10, 15% for 20, linear between, and
3/k above 20; every cap is at least 1/k, so the book stays fully invested.
Gross exposure is unchanged. Off in backtests (`fit_capital=False`).

**Halts.** Each of these trips the deployment's own switch and stops it:
orders still UNKNOWN after asking the broker; a replayed, already-traded day
producing an order the journal never saw (the data changed after the fact);
engine holdings ≠ broker positions. A stale panel is reported, not halted.
Live mode is refused in code until the Kite adapter has placed a supervised
order (T-3336) and live limits exist.

The overnight Nifty-futures book also records, in its state's `inputs`, the
Nifty open and close, VIX open, close and previous close, and the signal it
read for every day it walked. A later run that finds a past day's signal
changed halts with those values beside today's ("Then … Now … Changed …");
one that finds the values changed but the signal not continues with a
warning. Added after the 2026-10-14 halt, whose earlier 13 Oct values could
not be recovered because the landing file had been fetched again.

**Paper cash flows (ADR-076).** Add/withdraw requests are recorded on the
deployment with their amount, entry time and latest decided date. They do not
change the original capital or rewrite earlier orders. Replay applies a flow
at the first later decision close and forces a rebalance there; fills settle at
the following close. A withdrawal sizes the new book after the requested
outflow and is paid only after the resulting sells settle. The overnight book
settles its prior position at the open, then applies a flow before sizing the
new close position. The state reports contributed capital (`invested`),
applied flows and pending flows separately. `total_return` is time weighted,
so an external deposit is not reported as a gain. Live deployments reject
flows.

**A deployment's report (`deploy/analysis.py`).** `GET
/api/deployments/{id}/report` puts a paper or live deployment's own record
through `reports.build`, the backtest report's builder, so the page at
`#deployment/{id}` has the same tabs: equity, drawdown, calendar returns, round
trips, per-instrument attribution, fills. Three differences. The curve is the
time-weighted one (`risk.book.growth`) scaled to the starting capital, from the
start date at that capital, so a deposit is no return and day one's costs are.
Rupees made (equity less money put in) and each flow are shown beside it, and
the attribution reconciles against those rupees. The strategy's longest stored
backtest's metrics sit beside its own. Every run writes all fills to
`fills.json`; the state keeps only the last 200, and a report built from those
says so.

**Where a return came from (`attribution.py`, research 114).** Every report
read through `/api/report` or `/api/deployments/{id}/report` carries an
`attribution`: holdings (share of profit from the best 1/5/10, names for half
and four-fifths, the return without the best 1 and 5), profit by NSE sector and
industry (today's labels, A-061), each year's return and largest contributor,
and a daily regression on the Nifty 50 (beta, R², alpha, the return beta alone
earned). Computed on read, so old reports have it; shown in the report's
Attribution tab. Brinson attribution needs benchmark sector weights, not held.

**Detailed attribution (`attribution_detail.py`, research 115).** On request
(`/api/report/attribution`, `/api/deployments/{id}/attribution`; the report's
"Run detailed analysis"), the daily book is rebuilt from the fills and today's
adjusted closes and checked against the stored equity (views hidden beyond a
2% gap). From it: exposure by year (invested share, holdings, effective
holdings) and frozen positions (held after the stock's last price); Brinson-
Fachler by sector each month against the equal-weight point-in-time 250,
Carino-linked; a monthly regression on market (Nifty 50), size (turnover),
momentum (12-1) and low volatility built from the panel; Euler risk shares of
the final book; the three deepest drawdowns and best/worst months with their
drivers; trades by holding period and sector; capacity at 20% of median daily
turnover; rolling twelve-month beta and alpha. A month-end base for every stock
is cached in `data/derived/attribution_monthly.json`, rebuilt when the panel
changes.

**Minute-bar strategies on paper (`deploy/intraday_book.py`, ADR-078).** A
coded intraday signal deploys on the instrument its library result was
measured on (NIFTYBEES, QQQ/SPY or BTCUSDT). Each run scans that instrument's
minute bars with `paper_scan.scan_symbol`, the scanner its backtests use, from
the deployment's start to yesterday, and sends every bracket leg through the
deployment's OMS; costs are `bracket._cost` on the paper fill. It trades from
the day after it is made, reads nothing on or before `mandate.yaml`'s
`forward_evidence: holdout_end` (no such line: it cannot deploy), halts if a
past day gains a trade, and is flat at every close. US minute bars are fetched
by the book itself; Indian ones need the day's Kite login. Not yet: deposits
and withdrawals, sizing on current equity, Tweezer Bottom (no adopted
instrument), and the option structures.

**Research studies on paper (`deploy/study_book.py`, ADR-078 stage 2).**
Twenty-seven study strategies deploy. Twenty-two come from thirteen modules
that share one shape (`run_all` → `_run` inside `EVAL_START..DATA_END` → each
run's `id` and full `trade_log`): the book runs the module's own `run_all`
with those two constants set to the paper window and its `rs` loader held to
files starting after the holdout end (`load_days(since=…)`), under a lock, and
puts all three back. Five are research 112's cross-sectional screens: the book
scans every F&O stock (`cs.scan(since=…)`) for the one screen and records every
trade handed to `cs.report`, not the 2,000 it keeps. Checked 2026-10-17 on the
studies' own 2024 windows: Donchian 530/530, initial-balance failure 774/774
and Hikkake 915/915 trades identical; overnight reversal 56,974/56,974 and NR7
42,380/42,380 trades captured. Quantities scale by deployment capital ÷ study
capital; each trade is two OMS orders (shorts sell first), NSE intraday
charges on the paper fill. Not yet: the India and stock session papers, the
gold-stock screen, the stock candidates, the FII screen, the cost-aware ML
study, MCX gold and the option structures (each a different engine).

**Gated intraday rules on paper (`deploy/rule_book.py`, ADR-142).** H-0052,
H-0065, H-0096 and H-0098 passed the gate (PROMOTE or PAPER) but are not
rank-and-hold cards. Each has a generator that re-applies its rule to minute
files starting after the holdout end and returns `study_book`'s trade shape;
`study_book.run(trades_for=..., block=...)` then trades them unchanged.
H-0096 shorts each stock on its first F&O ban day (the nightly `fo_ban`
report) 09:20-15:10, ten slots of the capital. H-0098 shorts the same stocks
at the 09:15 auction print and covers at 15:10: a variant, because its
backtest's closing-auction exit is out of reach of an intraday short, and the
state says so. H-0065 ranks every F&O stock on its 20-session mean overnight
move and trades the two deciles 09:20-15:10, capital spread evenly; it waits
21 sessions after the holdout end. H-0052 buys NIFTYBEES on a session whose
next weekday is in NSE's holiday list (`make holidays`). Deploying needs a
PROMOTE or PAPER verdict; the live preflight still needs PROMOTE.
The console lists every hypothesis whose latest gate verdict is PROMOTE or
PAPER (`strategies.gated_hypotheses`, read at request time), at stage
`promoted` or `paper_candidate` until a paper book starts; the Live tab's
"Passed the gate" table deploys them. A card with several configurations is
listed but cannot deploy: choosing one after the gate is a selection it never
priced. Each configuration is listed as its own step (feature, top N,
rebalance), so a card whose configurations share a feature still reads clearly.

**Full history and recommended settings (ADR-143).** `make full-history`
backtests the fifteen gated strategies from 2016 (daily) or 2021-08-20
(minute) to the holdout end, after recording one holdout read per strategy:
the operator chose to spend the holdout on them. Each run is stored in the
result store; each strategy's setting (dates, universe, tier, asset class,
timeframe, capital) is served as `recommended` and fills the library's
backtest controls when the strategy is opened.

---

# Part V — The workbench

## 7.0 The look (ADR-090, ADR-093)

Four colours (Apple's system blue, green, red and orange) on frosted glass,
defined once in `web/app/tokens.css`:

| Colour | Token | Means |
|---|---|---|
| Blue | `--brand` | an action, the page you are on, the selected thing |
| Green | `--up`, `--clear` | a rise; on a result, cleared the noise bar |
| Red | `--down`, `--fail` | a fall, a refusal, a failure |
| Amber | `--caveat` | a warning: assumed, unrecorded, stale |

Charts that need more series use `--series-1..8` (the four, then a light tint
of three, then grey). Corners: `--r-sm` 12px on controls, `--r-md` 16px on
panels, `--r-lg` 22px on cards, pills on toggles and buttons.
`web/app/terminal/theme.css` loads after `terminal.css` and `shell.css`, and
`glass.css` after it. `--surface` is translucent: three soft glows sit behind
the page and each card blurs them (`--glass-blur`), with a white hairline edge.
The selected page or view is a raised white thumb on a grey track, as in iOS.
`--surface-solid` is for what must hide the page; dialogs use heavier glass.
Dark mode redefines tokens only, apart from three hover tints.

## 7.0a The Charts page (ADR-114)

NSE symbols are drawn only by `OwnChart` from `/api/history`, the same bars a
backtest reads; other venues use TradingView's free embed. The chart's
drawings (horizontal, vertical, trend) are stored as prices and dates, not
pixels, so they stay put through zoom, scroll and the log scale; an SVG layer
over the price pane converts them on every redraw. Clicks are read from the
DOM, because the library drops a second click within 500 ms while it waits for
a double click. Indicators come from `web/lib/indicators.ts`: SMA; EMA seeded
with the SMA, k = 2/(n+1); RSI with Wilder's smoothing; MACD 12/26/9;
Bollinger with the population standard deviation. The macro charts plot
`macro.all_series`: one point per sweep, last six months, skipping the fake
DXY test row.

**Timeframes.** 1, 5, 15 and 30 minutes and 1 and 4 hours come from
`/api/history/intraday`: the minute archive read by `intraday.store.fetch`
(one bar per timestamp) and rolled up by `store.resample`, whose buckets start
at each session's first candle, so a 4-hour chart has 09:15 to 13:15 and a
short 13:15 to 15:30. Minute bars exist for NSE stocks only, and the window is
bounded (5 calendar days for 1 minute, up to 400 for 4 hours). Intraday times
are IST wall-clock written as UTC epoch seconds, so the axis reads 09:15.
Day, week and month come from the daily bars; a week runs Monday to Sunday
and a candle is dated by its first trading day (`web/lib/bars.ts`). Drawings
store times as seconds and land on the candle that holds them in any
timeframe; a line outside the loaded window is not drawn. Ranges (1D to All)
are spans of time, not counts of bars.
Equity daily bars are drawn split-adjusted (`/api/history?adjusted=true`), the
prices a backtest reads; minute bars are raw. Intraday answers are kept in the
API's memory for the day (24 at most), because a 4-hour chart reads 400 days
of minute files and took 7 to 8 seconds.

## 7.1 The strategy builder

Tools → Strategy Builder (`web/components/terminal/StrategyBuilder.tsx`,
`src/eulerlab/builder/`). A strategy is declared in five steps, in the order it
acts: what it may trade (market, universe, instruments, price and turnover
filters), when it buys (rules), when it sells (rules), how much it holds (slots,
equal or volatility-scaled, optional ranking) and what stops it (stop loss, take
profit, trailing stop, maximum days held). Research 062 and ADR-058.

A rule is `indicator comparator operand`, e.g. `Close crosses above SMA(50)` or
`RSI(2) below 10`, combined as all or any. The 22 indicators are streaming
(`builder/indicators.py`): RSI and ATR use Wilder smoothing, EMA is seeded with
the SMA, Donchian high/low exclude the current bar.

**The spec is data, compiled to the one `Strategy` interface.** `BuiltStrategy`
returns target weights like any other strategy. Each instrument's position is
re-derived from the view by replaying the rules bar by bar — entry, then the
first of exit rule, stop, target, trailing stop or holding limit — so stops need
no memory between calls. The replay is cached per instrument and extended by
new bars; the cache is discarded when the view's history is no longer a prefix
of the one it was built on, which is what a newly knowable corporate action
does. A cached replay and a fresh one give identical weights (tested).

Decisions are made on each close (`rebalance_every = 1`). Entry price is the
signal close; stops are judged on closes. Long only.

**Holding without drift.** A builder strategy sets `hold_unchanged`: both
engines leave a held position at its quantity while its target weight is the
same as at the previous decision, so only entries, exits and changed weights
trade. Without it, daily rebalancing to exact weights turned a 10-slot golden
cross into 1,853 round trips in 800 days; with it, 39.

**Saved per workspace** as `workspaces/<id>/strategies/b_<name>.json`. A builder
strategy is listed in Strategies and backtested through `/api/run/batch` like a
registered one. Its spec digest goes into the run's params, so an edited
strategy is never served from cache and every result names the rules behind it.

The language-model draft and sandboxed code routes (`authoring/`) still exist on
the API; the builder page no longer offers them.

## 7.1a The research library

Tools → Research Library (`web/components/terminal/ResearchLibrary.tsx`,
`src/eulerlab/research/library.py`, `/api/research/*`). One YAML file per paper
in `research/papers/`: title, authors, year, link, **summary**, **trade idea**,
**implementation logic**, red flags, what the source itself reported, an
optional hypothesis (`H-NNNN`), and links to the strategies that test it.

A link is `builder` (a saved Strategy Builder spec), `registered` (a coded
strategy) or `tweezer` (the Tweezer scanner on a stated candle size). Each link
shows its latest stored result; builder and registered links backtest through
the shared Backtest dialog and `/api/run/batch`, Tweezer through
`/api/tweezer`. "Build its rules" opens the Strategy Builder with the paper
remembered for the browser session; the next save links the new strategy to
the paper and moves an `idea` to `specified`.

ADR-059.

New papers can be drafted from operator-pasted source text with the
assistant provider. The assistant panel and the Research Library list the
`offered` providers in `config/llm.yaml`: Groq `openai/gpt-oss-120b` (the
default) and every current Claude model, which are paid, used only when picked,
and never a fallback (ADR-095). Claude goes through Anthropic's SDK
(`assistant/anthropic_api.py`), which translates the chat shape, passes thinking
blocks back, and turns a refusal into a model failure; Anthropic keeps API data
up to 30 days and does not train on it (research 129). When `assistant` is OpenRouter, the API
can still list its live free-model catalog filtered for ZDR endpoints and tool
support, refreshed every ten minutes, and checks a requested model against it. Inference still
enforces ZDR and collection denial. The endpoint uses the assistant's approved-host, retention
and `.env` redaction checks; it returns a draft and never saves it. Source text
is not persisted, and a link alone is not fetched. Neither draft depends on
one model: unless the operator picked a model, `chat.complete_any` moves on to
the last model that answered, then each configured provider the locks allow,
then OpenRouter's current free ZDR list. A model that turned a request away is
skipped for 30 minutes; a host whose key or connection failed is skipped for the
rest of the walk. At most three models may actually answer (each spends free
allowance), one try is cut off at 150 s and the walk at 420 s, inside the web
proxy's 600 s (`experimental.proxyTimeout`). A reply the caller cannot use
(no JSON, or code the sandbox rejects) counts as that model failing. On a paper page, **AI code &
backtest** uses the selected provider for a strategy, validates it with the existing
authoring sandbox, then submits it to the existing Tier B backtest job. The
generated source and single-run results are shown for review. This path does not
save or link the generated strategy, and the result is not robustness evidence.
ADR-073.

### Tweezer Bottom, to the operator's report

`intraday/tweezer.py` and `scan.py` follow the operator's June 2026 report
(`research/papers/protective-collar-2026-tweezer-bottom.yaml`): 15, 30 or
60-minute candles rolled up from Kite minute bars, anchored at each session's
first minute (`store.resample`); indicators over the last 100 candles across
sessions; no signal from a candle closing at or after 15:00; stop at the
pattern low minus the larger of 0.1% and one ATR; half at 2R, rest at 3R, a
0.5% trail after +1.5R, no breakeven move. The breakout candle straight after
C2 may fill (`bracket.run(first_fillable=0)`). `max_hold_sessions` sets how
many sessions a trade may stay open; 1 is flat at the close. `make
tweezer-report` re-measures the report's window and prints both sets of
numbers (research 063). From the Strategies page Tweezer backtests through the
same intraday batch path as the paper signals (`intraday_runs._run_intraday`),
on 15-minute candles, flat at the close, up to 50 names.

### The Strategies table

`/api/fleet` gives each strategy a `table` block (`server._table_figures`):
annual return over the period its report says it traded, trades and win rate
from the report (`reports.headline`, cached by file time), NIFTYBEES over the
same period for NSE runs (`benchmark.nifty_return`), and a verdict that is the
bar put in words — `beats_bar` is exactly `clears_bar`, `positive` a positive
Sharpe and return luck could explain, `loses` a loss, `not_run` no result.
`web/components/terminal/Library.tsx` draws it as a sortable table with a
side panel.

### Indian-equity paper strategies

`backtest/india_papers.py` holds one strategy per paper in `research/papers/`
on Indian equities, registered as `india_*` and built through
`published.BUILDERS`. Cross-sectional ones (`RankTop`, `LowBeta`) take the
whole panel and keep the 250 most-traded stocks by median turnover over the
previous 60 sessions **at each decision date** (`liquid_universe`), because the
named universes are not point-in-time (HISTORY #16). Calendar ones
(`IndexCalendar`) hold NIFTYBEES over the days a rule selects, deciding two
trading days ahead from the panel's calendar (A-041); the expiry day is read
from `nifty_expiries.json` when it is built, with the weekday rule as the
fallback outside its range. `make india-papers`
runs them all and writes `data/derived/india_papers.json`.

**Indices as instruments.** A run whose universe is `nse_indices`
(`market_history.INDEX_UNIVERSE`) and whose instruments are index names gets
the index levels as price rows (`index_panel_rows`), keyed `IDX:<name>` so no
corporate action adjusts them. The engines then hold an index as they hold a
stock, at stock-delivery costs; `SectorRotation` runs this way. Nothing can buy
an index at its level, so such a result is an upper bound on a fund tracking it.

**Trades the engines cannot express.** Both engines fill a decision at the next
close, so a close-to-open trade has no target-weight form.
`research/session_studies.py` calculates the overnight papers on Nifty futures
(one contract per leg, never across a roll, the futures cost model on every
round trip) and the index gross, and the expiry-day SIP by XIRR. They are
calculations, not runs: no fills, no result store, no trial. NIFTYBEES is not
used for them: an ETF's open in the panel is its first print, which can be 20%
from its value (research 066).

**An ETF is not a share to the cost model.** A delivery leg in a fund unit
(an `INF` ISIN) pays STT of 0.001% on the sale and none on the purchase, not
the share's 0.1% on both (A-047). Both engines and the paper executor learn
which symbols are fund units from the rows (`vector.fund_symbols`) and pass it
to the one cost path; until 2026-10-07 they charged ETFs the share rate
(HISTORY #18).

## 7.1b The paper agent (ADR-084)

`make paper-agent TOPIC="..." [LIMIT=5]` (`research/paper_agent.py`,
`research/paper_search.py`) goes from a topic to drafts the operator reads.
Cards stop there; papers go into the library (ADR-126).

    price the search -> the sources in research.yaml (arXiv q-fin, OpenAlex, SSRN, NBER, CORE, Semantic Scholar)
      -> one per paper across sources -> closest to the topic first, sources taking turns
      -> drop papers already known by any name, and ones sharing no topic word
      -> read arXiv HTML (first 16,000 chars), the abstract, or Crossref's, else OpenAlex's
      -> research_agent model (one retry) -> JSON reply -> library.Paper + Card
      -> research/papers/<id>.yaml for every paper judged, even "not a trading idea"
      -> card.validate + critic.review
      -> research/agent_drafts/<run>/<paper>/{paper,card}.yaml, review.txt, draft.json
      -> research/agent_drafts/<run>/run.json: every paper's outcome and why

**Every paper read is kept (ADR-126).** A paper the model judged not a testable
trading idea goes into the library with status `rejected` and the reason in its
trade idea; a drafted one goes in with status `idea`, and approval links its card
to it. So the library grows with each run and no paper is read twice. The
abstract itself is never written into the repository (Crossref warns some are
the publisher's copyright, research 144): only the model's summary.

**Sources and one paper under many links (ADR-129).** `paper_search.SOURCES`:
`arxiv`, `openalex`, `ssrn` (OpenAlex works whose source is SSRN, `S4210172589`;
SSRN's own site refuses robots), `nber` (Crossref works with DOI prefix
`10.3386`), `core` (CORE's open-access index, every topic content word required
in the abstract, 6 s between searches) and `semantic_scholar` (its relevance
search in economics and business, 1 s apart, a 429 retried twice after 5 s and
10 s; ADR-131). `config/agents/research.yaml` `sources:` lists which are
searched. Keys are read by `paper_search.api_key`, which loads `.env` and
accepts the standard name or the operator's spelling (`OPENALEX_API_KEY` or
`OPEN_ALEX_API_KEY`, `CORE_API_KEY` or `CORE_API`, `SEMANTIC_SCHOLAR_API_KEY` or
`Semantic_API`); CORE's goes in an `Authorization: Bearer` header and Semantic
Scholar's in `x-api-key`, never in the URL.
`paper_search.Known` holds every name of every paper in the library, staged, or
read and judged: DOI, arXiv number without version, SSRN number (page link or
`10.2139/ssrn.N`), NBER `wN`, CORE work id, Semantic Scholar paper id,
normalised title, and the title's significant
words; a candidate sharing a name, or 85% of a title of five or more words
(A-099), is `known`. A paper whose read failed is not, so it is tried again.
`make papers-duplicates` lists library pairs that look like one paper.

**Which papers are read.** Candidates are sorted by the share of the topic's
content words (first five letters, so "momentum" meets "moment") their title and
abstract use; one with none is `off topic` and not read (A-097). A paper with
under 200 characters of abstract and a DOI is looked up on Crossref, one request.
A model's reply that writes a text section as an object or a list is turned into
lines, not dropped. A failed model request is tried once more after 10 s, except
when the budget is spent.

**Order matters.** The search is priced before anything is fetched. An
unaffordable search (`budget.price_search`) reads nothing. Known papers
(matched on title or link, in `research/papers/` or an earlier run) are never
sent to the model again.

**What the model writes, and what it doesn't.** It writes the summary, trade
idea, implementation, red flags, claim, rationale and configurations. Code
sets the title, authors, year, link and fetch date from the search result. Code
also sets the holdout date (`scout.HOLDOUT_START`) and the card id. A staged
card has id `PENDING`; the next free `H-NNNN` is taken only at approval. A URL
in the reply is dropped. Each draft gets one more red flag naming the model and
how much was read. The reply must parse into `paper_agent.Reply`, or that paper
fails and the run goes on.

**Where text goes.** The prompt goes to the provider named `research_agent` in
`config/llm.yaml` (Groq `openai/gpt-oss-120b`, research 123) through
`assistant.chat.complete_any`. It passes the same host, zero-retention and
redaction locks as the assistant, and falls back to other models the same way.
If Groq's key or ZDR confirmation is missing, the run says so and uses the
`assistant` provider. Paper text is not stored. Drafts are spaced 60 s apart
(Groq allows 8,000 tokens a minute), and arXiv requests 3 s apart (its terms).

**Approval.** `make paper-agent-approve DRAFT=<folder>` checks the card again
with `card.validate` and refuses an incomplete one. It writes
`hypotheses/H-NNNN.yaml` as `status: draft` through `card.write`, which never
overwrites, and saves the paper to the library linked to that id with status
`specified`. It marks the draft `approved.json` so it cannot be approved twice.
The new card is not registered, so the gate ignores it. Whether to spend a
trial on it is still the operator's separate decision (`make research
CRITIC=H-NNNN`, then registration). `make paper-agent-list` shows drafts not
yet approved.

**What it cannot do.** It does not backtest, register, validate or write to the
trial ledger. `tests/test_paper_agent.py` reads the two modules' imports and
fails on any import of `backtest`, `validation`, `gates`, `gate_run`, `batch`,
`optimize`, `oms`, `deploy`, `paper` or `features.trials`. It also runs a full
draft and approval with the ledger's `append` set to raise an error.

## 7.2 The sandbox: how "paste code" stays safe

Executing arbitrary Python would discard the lookahead firewall, because
arbitrary code can open the panel file directly instead of going through a
`MarketView`.

The insight is that the danger was never *executing code* — it was executing
code with **reach**. Three layers remove it:

1. **Allowlisted AST.** `import`, `while`, `class`, `try`, `with`, `global`,
   `del`, decorators, generators and `async` are rejected before compilation.
   Anything not on the list is rejected too; the default is no.
2. **Allowlisted attribute names.** Not merely "no dunders" — a name must be on
   the list to be readable at all. This closes
   `().__class__.__bases__[0].__subclasses__()` and every variant.
3. **Replaced builtins.** `open`, `getattr`, `eval`, `exec`, `type`,
   `__import__` and `globals` **do not exist**. No name in scope returns a
   module, a class, or a file.

Names are resolved at submit time, so `open(...)` fails immediately with
"`open` is not available" rather than as a `NameError` hundreds of rebalances
into a run.

> **Not solved (S-021):** this stops code reaching *data* it should not see. It
> is not a defence against a hostile adversary — a determined person can still
> write an expression that runs for a very long time. `while` is banned and
> `range` is capped, but the real protection against a runaway strategy is the
> wall-clock timeout imposed from outside.

## 7.3 The language model is the least trusted component

- **It drafts; it does not decide.** Output is validated by code that can
  reject it. A hallucinated feature name produces an error listing the ten that
  actually exist.
- **The operator sees it before it runs.** Drafting starts no backtest.
- **Provider-agnostic.** Any OpenAI-compatible endpoint; the default is local
  Ollama, which is free, has no quota and sends nothing anywhere.
  Three roles in `config/llm.yaml`: `default` (Ollama, for the translator and
  the audit), `assistant` (Groq `openai/gpt-oss-120b`, the chat panel's default; `offered` adds the paid Claude models) and `research_agent` (Groq
  `openai/gpt-oss-120b`, the paper agent). Research 123 has their free limits.

Neither mode can produce lookahead — not because the prompt says so, but
because the `MarketView` contains no future rows to reach.

## 7.4 What the interface refuses to do

- **It never spends a trial.** A web UI makes running things cheap, which is
  exactly what would let someone burn fifty trials in an afternoon by clicking.
- **It never promotes anything.** There is no route to the gate.
- **It never runs unvalidated code.**

Every result carries its caveats **in the payload**, so the warning travels
with the number rather than being a paragraph someone can style away.

---

# Part VI — Verifying it yourself

Two commands, and they answer different questions.

```bash
make verify        # is the repository healthy?  7 checks, ~922 tests
make acceptance    # does each sprint still work on real data?  11 checks
```

`verify` covers lint, types, tests, docs, the **engine** gate and the **chaos**
gate. `acceptance` runs each sprint's own acceptance command against the real
panel — a distinction that matters, because every unit test can pass while a
data artefact is stale.

Useful individually:

```bash
make chaos                                # kill it mid-order, 11 scenarios
make test-engine                          # the ten engine self-tests
make check-adjust                         # corporate-action mathematics
make gate-acceptance                      # 3 overfit strategies must all die
make attribution FRICTIONLESS=1 DAYS=800  # gap must be exactly 0.00
make reconcile-book                       # our positions vs the broker's
```

**Two commands cost something.** `make gate` and `make validate` each write a
permanent trial to the ledger and raise the bar for every future strategy.
Neither is in `verify` or `acceptance`, deliberately.

---

# Part VII — What is not real

Nothing in this section is a defect. It is a list of what has not been built or
verified, kept so nobody mistakes the system for more than it is.

| # | Not real | Consequence |
|---|---|---|
| S-015 | **No live broker adapter.** The only one is a simulator | Nothing here says anything about real fills, latency or rejection reasons |
| S-016 | Paper fills are instant and complete | `ACKNOWLEDGED` and `PARTIALLY_FILLED` are modelled but never produced |
| S-017 | Costs in paper use our own model on both sides | The "cost model error" term of the reality gap is **zero by construction** |
| S-018 | The reality-gap residual is an identity | It proves arithmetic, not understanding |
| S-019 | Kill-switch separation is by code, not by OS | A process on this machine can delete the trip file |
| S-020 | Kill-switch limits are round numbers | None derived from an observed distribution |
| S-021 | The sandbox has no CPU limit | A runaway strategy relies on an external timeout |
| T-906 | The cost model has never met a real contract note | Every rate is from a secondary source |
| T-907 | **Market impact is not modelled at all** | Any result involving thin names is optimistic |
| T-1317 | Sprint 8's IC figures used raw prices | Those numbers should not be relied on |
| T-1310 | Excess kurtosis ≈ 155 unexplained on one configuration | Fat tails not fully understood |
| — | Compliance (Sprints 29–30) | Static IP, broker confirmation, CA review — all outstanding |
| — | **No capital has ever been traded** | Nothing has been live |

---

# Appendix — The module map

177 modules across 22 packages. This maps the **packages**, not the files:
packages change rarely and files change weekly, so a per-file index would be
stale before it was useful. Every module carries its own docstring explaining
what it is for; this is the map that tells you which one to open.

## Data in

| package | what lives there | start at |
|---|---|---|
| `ingest/` | every source that lands raw data — Kite, Binance, Alpaca, Delta, AMFI, FXCM, news, screener. The largest package, and mostly one module per vendor | `landing_reader`, `manifest` |
| `record/` | live recorders for data that cannot be bought back later | `universe` |
| `bitemporal/` | the two-clock store: what was true, and when it became knowable | `store`, `provenance` |
| `master/` | the security master — what an instrument *was* on any past date, through renames and successions | `identity`, `succession` |
| `corp_actions/` | splits, bonuses, dividends, rights; the factor store that adjusts prices per `as_of` | `build_factors`, `adjust` |
| `quality/` | what is wrong with the data we collected, stated rather than cleaned away | `run`, `reconcile` |
| `fundamentals/`, `options/` | screener financials; options chains and no-arbitrage checks | `screener_parse`, `arbitrage` |

## Deciding

| package | what lives there | start at |
|---|---|---|
| `features/` | the daily panel, indicators, the feature library, IC | `panel`, `alt_panel`, `us_panel` |
| `strategies/` | the registry: every strategy declared, and the capability catalog | `__init__`, `catalog` |
| `intraday/` | the minute-bar engine — signals, the bracket executor, and one store per market. Every `*_screen` takes its daily summary, intraday charges, EMA and RSI from `screen_common`; a screen keeps only its own rule | `paper_scan`, `bracket`, `us_store`, `screen_common` |
| `backtest/` | Tier A vectorised and Tier B event-driven, plus the self-tests that check they agree | `vector`, `event_driven`, `selftest` |
| `costs/` | what a fill costs, on the venue it would actually trade on | **`router`**, `model`, `us_equity`, `delta_exchange` |
| `authoring/`, `llm/` | turning a description into a strategy, and the provider layer under it | `translate` |

## Judging

| package | what lives there | start at |
|---|---|---|
| `validation/` | the gate: CPCV, deflated Sharpe, PBO, stress, and the hash-chained ledger | `statistics`, `cpcv`, `ledger` |
| `research/` | costing a search *before* running it, and the hypothesis loop | `budget` |

Top-level modules carry the optimisation pipeline, and the order they run in is
in §5.5:

| module | what it answers |
|---|---|
| `optimize`, `optimize_run`, `optimize_store` | which parameter setting is best, and what the sweep cost |
| `intraday/tuned`, `intraday/adopted`, `adopted_run` | which setting the strategy now uses, and what it does |
| `optimize_walk`, `walk_run` | does the in-sample winner survive out of sample |
| `us_all_run` | does this signal work on US equity at all |
| `strategy_results` | every measured result, discriminated by the question it answered (ADR-047) |
| `evidence` | where evidence lives, and what the noise bar is charged for (ADR-046) |
| `prune_runs` | one stored run per strategy, denominator preserved |
| `results`, `reports` | stored runs and the detail behind one |
| `gates`, `gate_run` | the promotion gate |

## Acting

| package | what lives there | start at |
|---|---|---|
| `oms/` | the order state machine, write-ahead journal, kill switch, reconciliation | `states`, `journal`, `killswitch` |
| `broker/`, `paper/` | Kite session handling; the paper-trading runner and its attribution | `kite_login`, `runner` |
| `batch/` | running many strategies without losing the ones that finished | `runner` |

## Serving

| package | what lives there | start at |
|---|---|---|
| `api/` | the HTTP layer, and three modules that are *not* — panels, intraday runs, and the request shapes both need | `server`, `panels`, `intraday_runs` |

Both servers listen on 127.0.0.1 only: the API (`make api`, uvicorn on :8000)
and the UI (`next dev` and `next start` on :3000, `-H 127.0.0.1`). `next`
otherwise listens on every interface, which let any device on the Wi-Fi open
the workbench and, through its `/api` rewrite, the API. The operator uses it
from the Mac only (T-4384).

## Live data and plumbing

The remaining top-level modules. Small, and load-bearing in the way plumbing is:

| module | what it does |
|---|---|
| `quotes` | live prices: Zerodha first, Angel One when Kite has no token for the day (ADR-158), Yahoo last |
| `indices` | index levels — India from the broker, the world from FMP |
| `macro` | macro series from TradingView's keyless public scanner |
| `workspace` | what is shared between tenants and what emphatically is not (ADR-040) |
| `cloud_results` | results mirrored to the bucket the market data lives in (ADR-042) |
| `config`, `env` | typed config from `config/`, and one place that loads `.env` |
| `paths` | where data lives: `EULERLAB_DATA_DIR`, the one setting every `data/...` path is built from |
| `notify` | telling the operator when an unattended job fails |
| `jobs`, `scheduler` | the job table, and the process that runs it on a server (ADR-164) |
| `health` | one page: is the scheduler, the live book's clock and the kill switch alive |
| `oms/deadman` | trips the kill switch when an armed live book's clock goes quiet |
| `schemas` | **stub.** Not the order schema — that lives in `oms/` |

**Where data lives.** Every module used to spell `Path("data/landing/...")`
itself: 328 literals in 201 files, each one an assumption that the process runs
from the repository root on the operator's Mac. `paths.data_path("landing/nse")`
replaces them. It reads one setting, `EULERLAB_DATA_DIR`, and falls back to
`data` relative to the working directory, so the Mac behaves exactly as before
while a container or server points the same code at a mounted volume. The
setting may sit in `.env`; `paths` loads it before the first module-level
constant is built. `make hygiene` fails on any new `data/...` literal under
`src/` (`data-literal`), so the rule cannot erode one commit at a time.

**Postgres, when it is switched on (ADR-165).** `EULERLAB_DATABASE_URL`
unset, nothing changes: every store writes its files. Set, the trial ledger
reads and writes one table, `append_log`, for any ledger path under the data
directory; a path outside it (every test's `tmp_path`) stays a file, so both
homes stay tested. A row is the old file line byte for byte, because the
ledger's hash covers the JSON text (jsonb would reorder keys and refuse NaN).
The table refuses UPDATE, DELETE, TRUNCATE and any seq that is not the next,
so append-only is enforced by the database, where the file could only detect
an edit through the chain. An append runs under a per-stream advisory lock and
builds its hash from the row that really came last, so two processes logging
at once get 7 and 8, never two 7s. The switch is made in three steps:
`make db-migrate`, `make db-import` (copies each ledger file, refuses a file
that disagrees with rows already imported, then verifies the chain from the
database), then set the variable for every process. Switching on before the
import raises `NotImported` rather than reading an empty ledger, which would
shrink the noise bar's trial count. Order journals, `trials.jsonl`, the agent
log and the kill-switch log are still files (T-4558 to T-4561).

`api/` is worth a note. `server.py` held four unrelated jobs — parsing HTTP,
loading panels, running intraday signals, building reports — and the first three
have been pulled out. The seam is that **nothing in `panels` or `intraday_runs`
knows about HTTP**: they take a request object for its fields and return plain
dicts, which is why they could move and why keeping them in the transport layer
was arbitrary. `requests.py` exists because both the parser and the answerer are
entitled to know the shape of the question.

---

# Glossary

**Adjustment factor** — the divisor that makes prices before a corporate action
comparable with prices after it.

**Backtest** — simulating a strategy on historical data.

**Bitemporal** — storing both when something happened and when it became
knowable.

**Breakdown point** — the fraction of data that can be arbitrarily wrong before
a statistic becomes meaningless. MAD: 0.5. Standard deviation: 0.

**CPCV** — Combinatorial Purged Cross-Validation. Time-series-safe validation
using multiple train/test paths with purging and embargo.

**DSR** — Deflated Sharpe Ratio. The probability a Sharpe is real, adjusted for
how many things were tried.

**Embargo** — extra days dropped after a test block to stop serial correlation
leaking.

**Holdout** — data reserved and read exactly once, at the end.

**IC** — Information Coefficient. Rank correlation between a feature and the
return that followed.

**Idempotent** — doing it twice has the same effect as doing it once.

**Lookahead bias** — using information that was not available at the time.

**MAD** — Median Absolute Deviation, a robust measure of spread.

**MinBTL** — Minimum Backtest Length. Years of history needed before a Sharpe
is distinguishable from luck.

**OMS / EMS** — Order Management System (tracks orders) / Execution Management
System (sends them, enforces rate limits).

**PBO** — Probability of Backtest Overfitting. How often the in-sample winner
underperforms out of sample.

**Purging** — removing training samples whose label window overlaps the test
period.

**Sharpe ratio** — return per unit of volatility, annualised.

**Slippage** — the difference between the price you expected and the price you got.

**STT** — Securities Transaction Tax, an Indian statutory charge on trades.

**Survivorship bias** — testing on today's list of companies, which excludes
everything that failed.

**TERP** — Theoretical Ex-Rights Price, the correct divisor for a rights issue.

**Trial** — one strategy configuration evaluated. Counted forever.


## The daily data pipeline (ADR-061)

`ingest/daily_feed.STEPS` is the one list of daily steps. The Instruments button
runs it (`POST /api/data/feed`), as does `make feed`; `make daily` runs the same
steps plus those in `TERMINAL_ONLY` (Kite minute bars, the one-year crypto
backfill, the per-folder uploads, pruning). `tests/test_data_pipeline.py` fails if
`make daily` gains a step that is in neither.

`make daily` takes one dataset at a time (ADR-070): download it, upload its
landing folder, delete the local copy, then the next.
`make upload-tree TREES="..." DELETE=1` (`sync_cloud --only --then-delete`)
lists only that folder's part of the bucket and deletes only the files a
fresh listing shows there at the same size. The NSE files are deleted after
market history, the price panel, Nifty options and the paper books have read
them, and the US files after the US panel. The full `sync-cloud` sweep and
`prune-local` still run last. The button still mirrors once, at the end of
its own shorter run.

Two exceptions (2026-11-01, HISTORY #52). `macro/` is never pruned: its day
files are appended to by every sweep, and readers fetch any day that is not
local through the landing reader. And a tree upload never replaces a bucket
object with a **smaller** local file; it reports the file instead. A smaller
local copy is a pruned file recreated with part of its rows, and uploading it
would erase the rest from the store of record.

The bhavcopy mirror (`cloud.sync`, the `nse` manifest) replaces a bucket object
only when the bucket holds an **earlier landing of ours** of that key and the
manifest's latest landing is different (`SyncPlan.superseded`). NSE revises
the index closes after first publishing them; until 2026-11-01 those were
reported as mismatched and never sent, so B2 kept the short first file
(HISTORY #54). A bucket object that no landing of ours produced is still
reported and never overwritten. B2 keeps every version, so a replaced copy is
not lost. Data-quality findings name their segment, and a dataset is graded
only on findings for its own segment: five segments share the `nse` manifest.

`tools/restore_macro_days.py` repairs a `macro/` day that an older overwrite
shortened (T-4365): it reads every B2 version of the day, writes their union
(`macro.merge_day_versions`: every reading once, in `at` order) as the current
object, and reads it back. Dry run by default; it never changes `data/landing/`.

Launchd runs these jobs only while their plists are installed and loaded
(`make schedule ACTION=install JOB=...` writes the plist; `launchctl load -w`
loads it). From about 20 October to 2026-11-01 only `briefweekend` was loaded
on the operator's Mac.

Fundamentals is not in `make daily`. `make fundamentals-update` fetches,
uploads and deletes under its own `fundamentals` lock; launchd runs it on
Sunday at 10:00.

Order: NSE end-of-day → participant OI → index closes and delivery → market
history → price panel → Nifty options → **paper books** → mutual funds,
calendar, crypto, FX, news, index levels, option chain, US bars → US panel →
mirror (uploads only keys B2 lacks or holds at a smaller size) → census.

**US bars are fetched from the first of last month, not 2016.** The history
is in B2; `make us-bars FROM=2016-01-01` refills it. `alpaca.land_bars` first
restores from B2 any month file `prune-local` removed, and skips a month whose
B2 copy it cannot fetch, so it never writes a file with fewer rows than the
bucket's. A re-fetched bar that has not changed keeps its first
`knowledge_time`, so an unchanged file keeps its size and is not re-uploaded
(HISTORY #68, ADR-130).

**Nothing twice.** Every source skips files already in the manifest. Every
derived table appends only the days it lacks, and reads what it holds *inside*
its own file lock (`ingest/filelock.py`: `panel`, `us_panel`, `nifty_options`,
`market_history`, `paper_daily`), so two writers cannot both add a day. The
whole run holds the `feed` lock; `make daily` takes it through
`python -m eulerlab.ingest.filelock feed -- make daily-run`, and whichever
starts second is refused with who holds it.

**Coverage.** `ingest/coverage.table()` gives, per dataset, the last day held
(NSE manifest, last line of each derived table, census `latest`, paper
`traded_through`) against the day it should reach (A-051) and counts the
sessions between. Served at `GET /api/data/coverage`, shown on Instruments,
printed by `make coverage`. The census `latest` is the largest date named in
any key, not the largest file name.

**One dataset at a time.** Each coverage row carries `steps`
(`coverage.STEPS_FOR`): the fetch it derives from, then its build — the price
panel is NSE end-of-day → price panel; a paper book adds paper books. Its
Update button sends those as `only` with `mirror=false`; each group header
sends the union of its rows. `refresh` runs them in `STEPS` order whatever
order they arrive in. Unknown step names are refused.

**The panel and the paper books follow the data (ADR-062).**
`daily_feed.DEPENDENTS` adds downstream steps to any run: NSE end-of-day →
price panel and Nifty options; price panel → paper books; index closes →
market history; US bars → US panel. The panel step returns at once when its
last line already holds the manifest's latest cash day; the paper step replays
only books whose `traded_through` (or, while waiting, `panel_through`) is before
the panel's last day, all in one `run_all` so the panel is read once. Outside
any run, the API's lifespan starts `autoupdate.watch`, which calls the same
`catch_up()` every 300 s and skips while the `feed` lock is held.

**India from the close (ADR-079).** `make india-live` (launchd 15:31, weekdays)
runs `refresh(only=india_live.INDIA_STEPS)`, which is NSE end-of-day,
participant OI, index closes and delivery, and India minute bars, plus their
dependents. It repeats every 600 s until today's cash bhavcopy is in the NSE
manifest and today's minute bars are in the Kite manifest, or until 21:00 IST.
With no Kite token minted today, the bhavcopy alone is enough. A holiday exits
at once. `coverage.expected_nse` counts today from 15:31 (`NSE_DUE`). A session
is a weekday not in `coverage.nse_closures()` (past days with no bhavcopy, plus
NSE's published holiday list from `make holidays`, minus any day with a landed
bhavcopy), or a landed weekend session (`nse_weekend_sessions()`). An NSE
row whose only absent session is today reads `missing` with "today's data not
in yet".

*Provisional daily bars.* `provisional_daily.record(day)` builds one bar per
symbol from the landed minute bars: open of 09:15, high max, low min, close of
the last minute, and summed volume. A session is complete when its last candle
is 15:29, or 15:14 from 2026-08-03 (`session_ends`), when F&O stocks stop
continuous trading at 15:15 for the closing auction (A-053, HISTORY #29).
Anything else is left out and counted as incomplete. Lines are appended to `data/derived/provisional_daily.jsonl`
with `event_time` 15:30 IST and `knowledge_time` now. The set is re-appended
only when it changes. When the day's bhavcopy lands, a `superseded_by:
bhavcopy` line retires the day. `read(as_of)` is bitemporal: it ignores lines
known after `as_of`. The panel never reads this file. The company page shows
the bar beside the official close (`price.provisional`). Checked on 23 Oct
2026 against the bhavcopy for the 203 non-F&O symbols: open, high and low are
identical, and the close differs by a median of 26 bps (p95 92 bps), because
NSE's close is the 15:00–15:30 weighted average. For F&O stocks, NSE's close is
the closing auction price.

*Minute bars land only complete days.* `backfill_minute.last_complete_session`
switches to today at 15:31 (was 15:45), and `complete_days` drops today from a
chunk until today's last candle is a session end (15:29, or 15:14 for an F&O
stock), keeping the same key, so the next pass fetches today again. Older days
are landed as Kite serves them. The rule assumes Kite never stalls a non-F&O
stock at exactly 15:14 after 15:31.

**Minute bars (Kite).** `ingest/backfill_minute` plans its requests from the
manifest: for each symbol, the weekdays in the window that no landed range
covers, cut into 60-day chunks (`kite_minute.uncovered_chunks`). The window
ends at the last closed session (15:45 IST). A token is usable when it was
minted after the most recent 06:00 IST (`broker/kite_session.is_fresh`).

**Three buttons.** Update all data (`POST /api/data/feed`), Mirror to cloud
(`POST /api/data/sync`, upload only) and Delete local copies
(`POST /api/data/prune`, `dry_run` first; deletes a file only when the bucket
lists its key at the same size). All three hold the `feed` lock.

**Reaching the API.** The equity panel reloads when its file changes; the alt
panels (crypto, MF, FX, US) when the census changes; the US band cache is
cleared after a run.


## Telegram (ADR-063, ADR-068)

One bot, the operator's chat (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`), three uses.

**Out, when something happens.** `deploy/runner.run` ends by calling
`deploy/signals.announce`, so every route to a run reports: the mode, the
strategy's library title, each order placed on days the previous run had not
reached (side, quantity, symbol, price), then equity, cash and the next
rebalance. A halt or an error is sent once, when the status changes. A run
that placed nothing sends nothing. Delivery never raises.

**Out, before the close.** `make gap-signal` (`research/gap_signal.py`) reads
the Nifty 50 and India VIX live from Kite and sends the registered gap
strategy's decision: buy the future at the close and sell at the open, or no
trade. It says when it was read too early (before 15:15 IST) or too late.

**In, on request.** `telegram_bot.listen` long-polls `getUpdates` in a thread
the API starts (`make telegram-bot` runs it alone; the `telegram_bot` file lock
keeps it to one listener). `COMMANDS` is the whole vocabulary; the handlers
about deployments are in `telegram_bot.py` and the rest in `telegram_words.py`:

| Group | Word | Answers |
|---|---|---|
| Deployments | `status` | every deployment: mode, strategy, equity, return, last traded day |
| | `pnl` | each deployment's gain and last day's move, and the total by mode |
| | `positions [n]` | what deployment *n* holds |
| | `orders [n]` | its last ten orders |
| | `next [n]` | what it will hold after the next rebalance, and when |
| Market | `market` | stocks up, down and flat, the 20-session average move, volatility |
| | `movers` | five biggest rises and falls; unusual turnover on the last settled day |
| | `price SYMBOL` | a live quote if one answers, the last settled close, the year's range |
| | `company SYMBOL` | size, P/E, ROCE, ROE, growth, debt, promoters, industry median P/E |
| | `news SYMBOL` | the five newest held headlines that name the company |
| Research | `signal` | tonight's gap-strategy decision |
| | `strategies [word]` | the library's count by asset class, or a search of it |
| | `results ID` | a strategy's latest run and, if it was searched, the best of N |
| | `trials` | configurations tried, and whether the trial log's chain is intact |
| Machine | `brief` | `pnl`, `market`, `data`, `kite`, `kill` and `jobs` in one message |
| | `data` | which datasets are behind |
| | `jobs` | each `com.eulerlab.*` launchd job: running, clean, or failed with its exit code |
| | `kite` | whether today's Kite token is valid. Never the login link: it carries the API key |
| | `kill` | whether the kill switch is tripped, and its limits. It cannot trip or clear it |
| Assistant | `ask QUESTION` | the assistant's answer (ADR-064), with the model and tools it used |
| | `forget` | drops the last four questions and answers the bot keeps in memory |
| | `help [word]` | the list by group, or how to send one word |

**How a message is read** (`telegram_bot.answer`). A slash is optional. A word
may be its short form (`pos`, `p`) or any start that only one word has
(`mov`). *n* is a number from `status` or part of a deployment's name. A word
within one or two letters of a real one gets "did you mean" and nothing else.
A message of three words or more that starts with no word, or one ending in a
question mark, is treated as a question and goes to `ask`
(`EULERLAB_TELEGRAM_ASK=0` turns that off); a shorter stray message gets the
list. A stock is found by symbol or by a part of its registered name; several
matches are listed for the operator to choose from.

**How an answer is sent** (`telegram_bot.reply`). In pieces of up to 3,500
characters, split between lines, so nothing is cut. Each carries a keyboard of
nine words for a phone. "Typing" shows while a slow answer is worked out.

Messages from any other chat are dropped without a reply. No word places,
changes or stops an order, and a test pins the list of words.

**The gap strategy in the library.** `nifty_calm_rise_overnight` is a
`Declaration` that is not a `Strategy`: it holds a future from a close to the
next open, which neither engine can fill. The API runs it through
`research.gap_forecast.calm_rise_run` (`STUDY_RUNNABLE`) and records the result
under its own asset class and universe, with engine `overnight`.

## How the dashboard loads fast (2026-10-12)

Measured on the real panel (5.4 million rows, 746 MB), before and after:

| What | Before | After | How |
|---|---|---|---|
| Dashboard first paint (`/api/snapshot`) | 6 to 9 s | 0.4 s | The screen asks twice. `live=false` answers from held data and paints; `live=true` waits on the broker and swaps live prices in |
| "The last N days" of the panel | 1.2 to 1.9 s per request | 5 ms | The rows are in day order, so it is a slice. `_Panel` records where each day starts when it loads |
| Reading the panel (cold start) | 51 s | 13.5 s | Read a line at a time; `orjson`; parse each date once; build each row in one step, not ten; sort only the days whose symbols are out of order |
| First request after a restart | 29 s and up | 3 s | The panel is read in a background thread at startup (`EULERLAB_PRELOAD=0` to switch off) |
| Symbol counts (`/api/universes`, `/api/data`) | 0.6 s, 1.7 s | 3 ms, 0.4 s | Counted in the pass that loads the panel |
| A company page | 0.9 to 3.4 s | 0.3 s | Adjust one company's prices, not every symbol's; look on disk before listing the bucket |
| Loading 1,088 price factors | 0.6 s | under 10 ms | `BitemporalStore.append` places a record in order instead of re-sorting the list each time |
| UI JavaScript | 9.7 MB (`make ui`) | 0.67 MB (`make ui-fast`) | A built bundle, not the development server's |

**What the first paint shows (ADR-067).** Not always the settled close. Each
live answer that priced the universe without an error is saved to
`data/derived/last_seen_quotes.json`, one file, replaced whole.
`last_seen.newest` lays over the panel whatever is dated after the panel's
last day (India time): those saved quotes, and held minute bars if the minute
feed ran since. The newer source wins where both price a stock. Anything from
the panel's last day or before is ignored. The screen then reads "last seen
14:52" in place of "EOD", and "live" once the broker answers. A minute bar's
return is measured from the panel's close when its session is the next one,
and from the previous session's last bar otherwise. Reading the file takes
2 ms and checking the minute folders 40 ms; a minute file is opened only when
its name ends after the panel's last day.

A second pass on 2026-10-12 timed every read route and profiled the slow ones:

| What | Before | After | How |
|---|---|---|---|
| Options history, 30 days | 77 s | 4.7 s | `quotes_from_fo_bhavcopy(payload, underlying)` keeps one name's rows before parsing (a day's file is 35,000 contracts over 200 names); each file is decompressed in one call, not read a line at a time; and the history solves implied vol for the at-the-money row only (`_chain_payload(summary=True)`) |
| Live prices on the dashboard | 3.8 s | 0.8 s | Kite's OHLC endpoint, 500 symbols a call: 5 calls, not 12 to 16 (research 074) |
| Options chain, one day | 3.0 s | 0.3 s | The same filter |
| Routes that list the bucket (Instruments, option days) | 5 to 57 s whenever the five-minute listing had expired | the old listing at once | `available(..., stale_ok=True)`: a screen gets the listing it has and a background thread fetches the new one. Backtests and ingests never pass it |
| Strategies table, first open after a restart | 5.4 s | under 1 s | The benchmark series is read with the panel at startup |
| Strategies table, each open | 0.5 s | about 0.3 s | The results file is read once per request, not once per strategy; a strategy's runs once per question |
| Assistant's price lookup | 2.7 s | a few ms | From the panel in memory, not a scan of the 746 MB file |
| The wait after every batch run | 43 s | 2 s | The results mirror downloaded all 70 result files to compare them. It now skips a file whose size matches, the test `push` already used; `make results-pull` still fetches everything |
| A study run from Strategies | computed twice | once | The report-rebuild pass recomputed items that had just been computed and have no report to rebuild |
| Paper-book update, two deployments | about 29 s | 21 s | The faster panel read; `trading_days` and `by_symbol` no longer hash or sort what is already in order. Same equity to the paisa |

**The chain's forward.** The options screen prices every row with one forward
and discount factor, fitted from put-call parity across strikes (Theil-Sen,
`implied_forward_and_discount`). A fitted discount above 1 is a negative rupee
rate, so it is replaced by parity with the discount fixed at 1: the forward is
the median of `C - P + K` (`implied_forward_at_unit_discount`, T-4345). With no
fit, the exact-expiry future is used undiscounted.

None of these stores a result to reuse later. Each removes work that was being
repeated or was never needed. `tests/test_dashboard_speed.py` checks every
fast path against the slow one it replaced.

Still slow, and why: the live snapshot takes about 5 s because it asks Kite
for the whole universe in 16 calls of 200 symbols; it no longer blocks the
first paint. The first call to `/api/fleet` after a restart takes 2.7 s.

A third pass on 2026-10-16 timed every read route again, warm. Unlike the two
above, these **do** keep a result between requests, each dropped by the change
that would make it wrong (ADR-077):

| What | Before | After | How |
|---|---|---|---|
| `/api/window` | 1.1 s | under 1 ms | `PANEL.days(n)`: the day list built when the panel loaded, not two scans of every row |
| Options history, 30 days, warm | 3.2 s | 5 ms | One point per (underlying, day), kept: a landed bhavcopy never changes. First request after a restart is unchanged |
| Research Library list | 0.33 s | 43 ms | libyaml's `CSafeLoader` (same result on all 96 papers) and each paper kept until its file changes |
| `/api/risk/book` | 65 ms | 42 ms | Sectors and backtest summaries kept until the digest or a report changes |
| `/api/cloud/status` | 1.3 to 2.4 s | 3 ms inside 60 s | The bucket listing, dropped when this server mirrors; the Data tab shows its time and can list again |
| Dashboard with live prices, reopened | 3.7 to 4.8 s | 0.35 s inside 15 s | A complete live answer for the map is reused, and the movers band takes its prices from it. A mover Kite did not price goes to Yahoo only, and Yahoo is not asked for 10 minutes after a 429 |

Both snapshot deadlines were inert until this pass (HISTORY #23): `_bounded`
now returns at the deadline instead of when the broker finally answers.

**The panel in memory (2026-10-27).** The loaded panel took 2.8 GB on an
8.6 GB machine that was already 5.3 GB into swap, so every read and every
request slowed. `PanelRow` is now slotted (no dict per row), and each symbol
and ISIN string is stored once. `canonical_symbols` takes the renamed rows
out of each day and puts them back by binary search: 444,603 rows on all
2,916 days carry an older name, and walking every row of every day took as
long as parsing the file. The reader pauses the cyclic collector while it
allocates, and the API calls `gc.freeze()` after a load. A full collection
over 5.4 million tracked rows took 1.48 s, landing on whichever request
triggered it; frozen, it takes no measurable time. Measured by CPU time, read
side by side: 37.5 s → 27.4 s, and peak memory about 2.6 → 1.85 GB, with
identical rows (every field of all 5,420,230 compared). `make api` watches
only `src/` for reloads (`--reload-dir src`): uvicorn polled all 64,323 files
in the repo four times a second, a whole CPU core, all day.

**The panel's columnar copy (2026-10-27).** `read_panel` keeps a Parquet copy
of the renamed rows in `data/cache/price_panel.columns.parquet` (120 MB). The
copy records the JSONL's size and modification time, and is read only while
both match. The first read after a rebuild parses the JSONL (about 33 s of CPU)
and writes the copy; every read after that takes about 8 s. All 5,420,230 rows
are identical, value and type, to the JSONL reader. No copy is written if any
number is not already a float. While the read runs it holds the interpreter
lock, so a shorter read is what unblocks startup: `/api/data` took 0.29 s alone
and 4 s during a read. `data/cache/` is never uploaded (`make sync-derived`
mirrors all of `data/derived/`). It also holds the screens' saved bucket
listings (`landing_reader.LISTING_DIR`): after a restart a screen gets the last
listing at once and a new one is fetched behind it. Backtests and ingests
always list live. `/api/data` answers before the panel is in memory and starts
the read; the Data tab asks again until the counts arrive. After a restart:
`/api/data` 37 s → under 1 s, and `/api/instruments` 11.8 s → 0.15 s.

**Repeated reads removed (2026-10-27).** `filecache.FileMemo` keeps a parsed
file until its modification time or size changes. The landing census
(`manifest.load`) was parsed 16 times per dashboard snapshot, and each
strategy's result log once per row. `adopted.read()` sat inside a list
comprehension and ran 143 times per snapshot; it now runs once. News month
files are parsed once per content (`news._dated_rows`, keyed by a hash of the
bytes), and the outputs were checked identical on the real files. Warm
`/api/snapshot`: 0.68 s → 0.18 s. Each day's straddle point is kept in
`data/cache/options_history.jsonl` (`HISTORY_POINT_VERSION` retires old
points), and missing days are computed four at a time. The first options
chart after a restart waited 29 s.

The loaded panel also keeps each symbol's rows in day order (`_Panel.symbol_rows`,
built in the load pass). The company page reads its five years from there:
0.45 s of scanning the 746 MB file per page → 2 ms. It falls back to
`read_symbol_rows` when the panel is not loaded or the file has changed, and
for every symbol a rename touches (`panel.renamed_names`, kept in the copy's
metadata). For those the two readers differ: the loaded panel files each
ISIN's rows under its latest ticker, while `read_symbol_rows` takes the rows
stored under the ticker and then the rest of each ISIN. GOLDSHARE's 2021 ISIN
change and GATECHDVR's merger come out differently (27 of 494 renamed tickers
on 2026-10-27). The company page keeps the file scan for those, and that
reading is the right one for a stock page (T-4155). Company pages are keyed by
the ticker in the screener.in files, which lags a rename: HEG became HEGAM on
2026-09-22 and ICICIPRULI became ICICILIFE on 2026-10-23, with the same ISIN.
The file scan follows the ISIN forward and shows those stocks up to today. The
backtest panel files them under the new name, so it would show the HEG page
nothing. Both readings are right for their job: one instrument under its
current name for a backtest, the history behind a given ticker for a page. Of
253 renamed tickers that have a company page, 247 read the same either way.
`mandate.yaml` (52 YAML parses per strategy-table request) and the adopted
results are read through `FileMemo` (the strategy table 0.22 s → 0.07 s). The
coverage table slices paths instead of calling `Path.relative_to` 3,674 times
(0.16 s → 0.07 s). IIMA factor files are cached by path, a landed file being
immutable, so a new release is used without a restart; it had been cached per
segment for the server's lifetime.

**First loads after a restart (2026-10-27, second pass).** The first dashboard
snapshot took 3.9 s; it now takes 2.0 s, of which the live quotes are most
(0.18 s with `live=false`). The US band read all 259,000 rows of the US panel
for its last two sessions. `us_panel.last_sessions` reads blocks from the end
of the file, which `build` writes sorted by (day, symbol), until it holds one
day more than asked, and drops that possibly cut day: 12 ms, rows identical.
`us_panel.read` itself is parsed with orjson, shares one date and one string
per distinct day and symbol, and fills its slotted rows through the slot
setters with the collector paused: 1.2 s → 0.46 s, rows identical. The calendar band lists the bucket with
`stale_ok` (the saved listing, refreshed in the background), so it no longer
waits 1.3 s on B2. `/api/cloud/status` still lists the bucket on the request:
it is a live comparison, and the Data tab loads it on its own without waiting.
`/api/data` counted the landing trees with three `stat` calls per file on every
request (0.3 s); it now walks with `os.scandir`, one `stat` per file, and
reuses each count for `LANDING_COUNT_TTL` (30 s), cleared after a mirror.
`boto3` is imported where a client is made, not at the top of
`corp_actions.prices` and `master.build_master`: importing the panel took
0.22 s → 0.015 s, and the API starts about 0.3 s sooner.

In tests the order governor waits on a simulated clock (`tests/conftest.py`).
Paper runs send many orders at 5 a second and the tests slept through it for
real: 25 of `test_paper_attribution.py`'s 27 s. The limit is still enforced
and counted. Paper and live runs still wait in real time.

## Market context on the dashboard (research 120, ADR-080)

`/api/market-context` answers beside `/api/snapshot`, and the Dashboard's
India view draws it in five bands. Every input is already landed. Each
section is computed on its own: one that fails says why and the rest still
show. The whole answer is kept 60 s once complete.

| Band | Source | Definition |
|---|---|---|
| Indices | `index_history.jsonl` (FileMemo, 20 indices of 146 parsed) | Close and change over 1, 5, 21, 63 and 252 sessions. India VIX ranked against the previous 251 closes |
| Valuation | the same file | NSE's PE, PB and dividend yield, each ranked against its own history. PE only from 1 April 2021 (A-062): NSE moved it to consolidated earnings and Nifty 50's fell from about 40 to 33 overnight |
| Breadth | the price panel, last 520 sessions | Split- and bonus-adjusted closes in a days x stocks grid (`price_grid`, the factors `build_adjusted_index` uses). % of stocks above their 20, 50 and 200-day averages (90% of the window present). New 52-week closing highs and lows against the previous 251 closes. High-Low Index = 10-day mean of highs / (highs + lows) x 100. Stocks only: ISINs starting `INF` (funds, ETFs) are dropped. Lists show names with a 20-day median turnover of Rs 10 crore or more |
| Sector strength | `index_history.jsonl` | 20 NSE sector indices. Relative return = (1 + sector) / (1 + Nifty 50) - 1 over 5, 21, 63 sessions. Rising: 1-month relative now above its value 5 sessions ago. Phase: 3-month relative above or below zero crossed with rising. Trail: the same two coordinates (3-month relative; change of the 1-month relative over 5 sessions) at each of the last `TRAIL_WEEKS` (6) weeks, oldest first; the overview draws it as the sector rotation chart below Valuation |
| F&O positioning | NSE participant-wise OI, last 260 files | Long share = index futures long / (long + short), per FII, DII, Pro, Client; changes over 1 and 5 files; percentile against the earlier files. Options shown as raw net contracts. Parsed days kept in `data/cache/participant_positions.jsonl`; files only in the bucket are read in one background thread |
| Nifty options | `options_history("NIFTY", 6)` | PCR by open interest, max pain, ATM IV and straddle of the nearest open expiry, against 5 sessions earlier |
| Delivery spikes | last 21 lines of `delivery.jsonl` (read from the end of the 194 MB file) | Today's delivery % at least 1.5x its mean over the previous 20 sessions (75% of them present), among names with Rs 10 crore median turnover |

The breadth grid takes about 3 s the first time after a restart and is kept per
(last panel day, row count, factor file stamp); later answers take 0.14 s.

Participant files are listed as their own tree, `participant_oi`. They sit in
the bucket at `nse/participant_oi/...` while the local copy is under
`data/landing/nse/`. Listed as the `nse` tree, `landing_reader` asks the bucket
for `nse/nse/...` and finds only the local files (T-4162).

None of these figures has passed the gate. They are context. The page carries
each definition, and Sensibull's own statement that PCR and max pain "do not
have high predictive power". Not shown, because it is not landed: upcoming
results.

### FII/DII cash flows (ADR-098, research 128)

NSE publishes each evening what FII/FPI and DII bought and sold in the cash
market that day, in Rs crore, at `www.nseindia.com/api/fiidiiTradeReact`. It
serves the latest day only and ignores `?date=` (research 004), so the dataset
is capture-only: `make fii-dii` makes one request, lands the JSON under
`data/landing/fii_dii/cash/` dated by the payload's own date, and appends one
row to `data/derived/fii_dii_cash.jsonl` with `event_time` (15:30 IST on the
trade date) and `knowledge_time` (when the file landed). A day already in the
manifest is skipped, whether or not its file is still local. A payload without
both groups, with two dates, with net not equal to buy - sell (0.05 crore
tolerance), or dated after today is refused.

It runs in `make daily` (19:30), in every `make india-live` pass, and from the
Data coverage table's own button. `fii_dii_cash.rows(as_of=...)` drops rows
known after `as_of`. `/api/fii-dii` (`api/fii_dii_routes.py`) answers the
dashboard: today's buy, sell and net per group, net over the last 5 sessions
held and the month to date, the run of same-sign sessions, the last 60 nets and
up to 12 monthly sums with the days each covers.

The panel is `web/components/terminal/FiiDiiFlows.tsx` with its own
`fiidii.css`; every colour is a `--fd-*` token. It sits at the top of the
Big money tab. There is no free official archive of these figures (research
004, 126).

**History (ADR-099, research 127).** `make fii-dii-history MONTHS=12`
(`ingest/fii_dii_history.py`) fills the days before capture began. It fetches
one Trendlyne page per month (`.../cash-pastmonth/DD-Mon-YYYY/`, the month ends
of the last N months, then today). Each page carries about 20 days in the
`data-jsondata` attribute of the table `cash-table-main-pastmonth`. It also
fetches one page each from Groww and stockezee to cross-check. Every page lands
unedited under `data/landing/fii_dii/<source>/`, keyed in the manifest by its
date. A page already there is not fetched again, so re-runs only ask for
today's pages.

Requests are one at a time, at least 2.5 s apart, with one try each. A 403 or
429 stops the run. A Trendlyne row is refused when net is not buy - sell within
0.15 crore (each figure is rounded to 0.1). It is also refused when the date is
in the future, or falls inside the NSE cash bhavcopy manifest's range without
a bhavcopy. Past the manifest's last day, a weekday is enough.

Only Trendlyne rows are written, with `source: "trendlyne"` and the page's
scrape time as `knowledge_time`. So `rows(as_of=...)` never shows a backfilled
day before it was scraped. NSE rows carry `source: "nse"`; a row without
`source` is NSE's. A day already in the table is never overwritten, and
`make fii-dii REBUILD=1` puts NSE's days first and fills the rest from the
landed Trendlyne pages.

Each run compares Trendlyne with NSE and Groww on every figure, and with
stockezee on the nets. It lists any gap over 1 crore.

### The India tabs and the market pulse (research 121, ADR-081)

The India view has four tabs, kept in the address as `?view=`: Overview,
Sectors, Big money and Stocks to watch. The other markets keep the
single page. `market_pulse.py` turns the figures above into words; it adds no
data of its own.

| Card | Rule | Word |
|---|---|---|
| Trend (ADR-083) | Faber: last completed month-end close of Nifty 50 against the mean of the last 10 month-end closes; badge from the fall off the 252-day high | above Uptrend, else Downtrend; badge Correction at 10-20%, Bear market at 20%+ |
| Participation (ADR-083) | % of stocks above their 200-day average, and the High-Low Index | both 50+ Broad; both under 50 Narrow; else Mixed. Tag from the 50-day share: under 30 Washed out, over 70 Stretched |
| Fear | India VIX percentile over the previous 251 closes | above 70 Elevated; under 30 Calm; else Normal |
| Big money | FII index-futures long share, percentile against its own last 249 files | under 25 More bearish than usual; above 75 More bullish than usual; else Usual |

Trend and Participation use published rules (research 122, ADR-083); the Fear and Big money thresholds are ours. The cards are not added into one score. There is no
generated text (ADR-082): a card is a word, its gauge and a fixed definition
behind an info button.

| Figure | Drawn as | Data sent |
|---|---|---|
| Trend | Up to 24 month-end closes with the 10-month average dashed, the same months for both; the badge | `spark`, `spark_average`, `month_end`, `drawdown`, `badge` |
| Participation | Half-circle dial of the 200-day share, split at 50; H-L index and 50-day share beside it; the tag | `value`, `zones`, `high_low`, `above_50`, `tag` |
| Fear | Half-circle dial, three zones, a needle | `value` 0-100, `zones` |
| Big money | Long-of-100 bar with the usual (median) tick; 60-day line | `value`, `usual`, `spark` |
| Indices | Tile: close, today, year line, five horizon blocks shaded by size | `spark` per index |
| Valuation | Range bar: low to high since the start date, median tick, today's dot | `low`, `high`, `median` per PE/PB/yield |
| Sectors | Ranked bars against Nifty, or a rotation quadrant: across 3-month relative return, up its `momentum` (1-month relative now minus 5 sessions ago) | `momentum` per sector |
| Options | Number line: forward, forward ± straddle, max pain | `expected_move.low/high` |

Every definition, rule and caveat on the Dashboard opens from `Info`
(`web/components/terminal/Info.tsx`): a button that opens on tap, closes on a
second tap, a click elsewhere or Escape. Hover tooltips remain only for values.
The breadth series is still computed (Participation and the new-high lists use
it), but its chart is not drawn.

### One visual language for every screen (ADR-102)

Every terminal screen is built from `web/components/terminal/ui/`: `Info` (the
only place explanation lives, a tap-to-open button), `Heading`, `Stat`/`Stats`,
`Chip`, `Seg`, `Empty`, `Move` (signed change with an arrow), `Sparkline` and
`Bar` (a bar inside a table cell). A page's title carries its description in
an info button; the Tools cards do the same. Screens move onto the kit one per
commit on the `ui-revamp` branch (TASKS, UI revamp).

An `Info` popup is portalled to the `.terminal` root and fixed to the window
(ADR-119), so no card clips or covers it. `web/lib/placePopover.ts` places it:
below the button, or above when there is more room there; height capped to the
larger side, with the popup scrolling; slid sideways to stay 8 px inside the
window. It follows the button on scroll and resize.


On the Dashboard's India overview (2026-11-04, operator): Valuation is followed
by the sector rotation chart (`SectorRotation`); the US "Moving elsewhere" band
is replaced by NSE's new 52-week highs and lows (`HighsLows`, the Watch tab's
list); the cross-asset counts and the evidence band are gone. The US view keeps
its movers.

## The overnight book (ADR-066)

`deploy/overnight.py` paper-trades `nifty_calm_rise_overnight`.
`deploy.runner.run` sends that strategy's deployments there and every other
to the equity replay.

**Each day, in order.** Morning: a position bought last night is sold at the
contract's open. Close: if the day is GREEN with VIX down
(`gap_forecast.predict(Model.JOINT, day) == UP`), buy the nearest contract
expiring after today at its close. Only days held in both the index history
and the futures history are walked, so a day is never judged before its data
is complete.

**Money.** Quantity = floor(equity / (lot x close)) x lot, lot read from the
day's F&O bhavcopy. P&L on a round trip = quantity x (sell fill - buy fill),
less `cost_of_trade(Segment.FUTURES)` on each leg. A fill is the published
price moved against the book by the deployment's slippage. Cash equals equity:
a future is not paid for, and no margin is modelled.

**Shared with the equity books.** `make_oms` (journal, paper broker, kill
switch), `client_order_id(strategy, signal day, symbol, seq)` with seq 0 for
the buy and 1 for the sell, the halt when book and broker disagree, the state
file's fields, and the Telegram message on new fills.

**It halts when** a held position has no opening price, or a past day that was
traded through without a signal now shows one.

## Risk on the deployed book (ADR-071)

`risk/book.py` is arithmetic on values handed in; `api/risk_routes.py`
gathers them; `GET /api/risk/book` returns one payload for three views under
Live & Risk. It reads and never acts.

**The idea.** A deployment is days old, so its own returns cannot give a risk
figure. Instead today's holdings are run through the last 250 trading days:
for a holding worth `v_i` rupees today and a past day's return `r_i(t)`,

    pnl(t) = sum_i v_i * r_i(t)

is what this exact book would have made or lost on day `t`. Every figure
below is read from that series.

| Figure | How |
|---|---|
| VaR, 95% | the k-th worst `pnl(t)`, k = ceil(0.05 * days); a loss, in rupees |
| Expected shortfall | the average of those k worst days |
| Normal curve | `z * sd - mean`, z = 1.645 or 2.326 |
| Recent-weighted | the same with `sd^2 = sum w_t pnl(t)^2 / sum w_t`, `w` falling by 0.94 a day back (A-059) |
| Component VaR | `VaR * cov(pnl_d, pnl_book) / var(pnl_book)` per deployment; the parts sum to the VaR |
| Beta | `cov(r, r_m) / var(r_m)` against NIFTYBEES, over days both traded |
| Stress, market fall | `sum_i v_i * beta_i * shock`; a name with no beta takes 1 |
| Backtest band | for each horizon h, the 5th, 50th and 95th percentile of every h-day return in the stored backtest |

**Deposits and withdrawals are neither profit nor loss.** Each stored flow
carries `applied_day`, the first curve day whose equity includes it. Every
percentage on these pages, the paper trading page and the Telegram `pnl` reply
is the time-weighted return `rb.growth`:

    index(t) = index(t-1) * equity(t) / (equity(t-1) + flow(t)),   index(start) = 1

the rule `TierBResult.total_return` already used. Rupees made are equity less
the money put in (`Book.deployed` = capital + flows). The percentage printed
beside rupees made is those rupees over the money put in (`made_pct`,
`since_start_pct`), so the pair always agrees; the time-weighted figure is
`since_start` per deployment and `since_start_twr` for the book, and is what the
backtest comparison uses (T-4345). A deployment is named by the money in it
now, not its starting capital. Today's P&L subtracts that day's flow. Drawdown and the live line against the backtest band are read
from the index, never from equity: the backtest has no flows, and a withdrawal
is not a drawdown.

Fewer than 60 days of prices gives no VaR. A name with no price on a day is
flat that day, and the payload says what share of the book that covers. A
deployment that holds nothing at the close has no risk here, and each view
says so first. No verdict against a backtest before 20 days live.

`config/risk_watch.yaml` holds four warning levels. They colour a row; the
limits that stop trading are the kill switch's (section 6.5).

**A position held only overnight (ADR-072).** The futures deployment is flat
at every close, so holdings cannot describe it. It carries a `GapRule`: with
`N` the rupees of future today's equity buys, `g(t)` the open of morning `t`
over the previous close less one, and `H` the mornings the rule had been in
position,

    pnl(t) = N * g(t)  if t in H,  else 0

joins the book's series, dated to the morning. Its VaR "on a night it holds"
is the same nearest-rank figure over `{N * g(t) : t in H}` alone, and is
given only with 30 such nights. The book's VaR therefore averages quiet and
signal nights; the page shows both figures.

**Adding and removing.** Every active deployment is read on each request;
nothing registers one. A stopped deployment is in no figure and is listed
with what it made. A deployment's colour is its place in creation order, so
others keep theirs. Each row carries the book's VaR without it, and
`POST /api/risk/what-if` gives the book's VaR before and after adding a
strategy at a stated capital, sized as equal amounts of today's names (A-060).


### Loss limits that act (ADR-092)

After every run, `deploy/loss_limits.apply` reads the deployment's drawdown
from its own high on the time-weighted curve (`risk.book.growth`, so moving
money is not a loss) and compares it with two levels:

| Level | Default | What happens |
|---|---|---|
| `reduce_at` | 10% | a reduce-only window opens from the next session: sells fill, buys are refused |
| `halt_at` | 20% | the deployment's kill switch trips; status halted; `make kill-reset` to clear |

Defaults are in `config/loss_limits.yaml` (operator-owned, A-071); a
deployment's own `reduce_at`/`halt_at` win. A window is stored on the
deployment as `{from, to, why, by}`. The runner replays the deployment from its
start every day, so `ForwardExecutor` refuses a buy whose fill day is inside a
window before the OMS sees it, on every replay alike; the book and the broker
never differ. Live & Risk shows the drawdown against both levels on each paper
card, with **Reduce only** / **Resume buying** and **Change** for the levels.
Only the daily rebalancing book enforces reduce-only (S-050). A book not yet
run since loss limits existed has no measurement in its state; the API makes
the same calculation for its card, with no action attached, so the card never
waits a day to show the drawdown.

## Scheduled jobs

The job table is `eulerlab.jobs`: fourteen jobs, each with its IST time, its
command (a Makefile target) and the reason for that time. Two things read it.
On the Mac, `tools/schedule_daily.py` writes each job as a launchd plist
(`make schedule JOB=...`). On a server, `eulerlab.scheduler` runs the table as
one process (`make scheduler`, ADR-164); the section after the table says how.

| Job | When | Runs |
|---|---|---|
| `com.eulerlab.daily` | 19:30 every day | `tools/daily_guard.sh` (`make daily`, and a message if it fails) |
| `com.eulerlab.fundamentals` | 10:00 on Sunday | `make fundamentals-update` |
| `com.eulerlab.gapsignal` | 15:20 Monday to Friday | `make gap-signal SCHEDULED=1` |
| `com.eulerlab.agentspreopen` | 08:45 Monday to Friday | `make agents-preopen` (data, operations, pre-open brief) |
| `com.eulerlab.briefweekend` | 09:30 Saturday and Sunday | `make agent NAME=market_brief`: the markets-closed note, once per break (ADR-105) |
| `com.eulerlab.agentsclose` | 16:15 Monday to Friday | `make agents-close` (data, operations, portfolio, knowledge keeper, handbook). The after-close note runs in `make daily` once the day's data is in (ADR-105) |
| `com.eulerlab.agentsweekly` | 07:00 on Sunday | `make agents-weekly` (Quantpedia sync, knowledge keeper weekly pass, knowledge index, code review) |
| `com.eulerlab.agentsideas` | 17:00 every day | `make agents-ideas` (research, then the idea lab, then engineering, then memory to B2; ADR-128) |

launchd runs a missed job when the Mac wakes. That suits a data pull and not a
message tied to the clock, so `gap_signal.out_of_session` makes a scheduled
run say nothing on a weekend, an NSE holiday, or outside 15:05 to 15:45 IST.

### Running on a server (ADR-164)

`make scheduler` is the launchd replacement. Every 30 seconds it works out, in
IST, which slots of the table have come due since its last look and runs each
in its own thread, so a long `make daily` never holds up the 22:00 data agent.
It writes what it ran to `data/scheduler/state.json`, so a restart does not run
a slot twice, and a slot missed while it was down is handled by the job's
`catch_up` flag: a data pull runs late, within three hours (a gap in market
history cannot be bought back); a clock-tied job (the 09:16 live-price sweep,
the 15:20 gap signal, the 09:10 depth recorder, the 15:10 close sweep) is
skipped and the skip is logged, because run late it would mislead. A non-zero
exit is reported to Telegram as `daily_guard.sh` reports `make daily`. Every
run is a line in `data/scheduler/runs.jsonl`; `data/scheduler/heartbeat.json`
says when it last looked. It knows nothing about NSE holidays on purpose: each
job already decides what a holiday means for it, and two places deciding would
disagree.

`make health` (`eulerlab.health`) is the one page: the scheduler's heartbeat,
each job's latest slot against its run, the live book's clock, and the kill
switch. It exits 1 when anything is red, so it is also the containers' health
check, and `GET /api/health` carries it under `ops`.

**The dead-man switch** (`oms/deadman.py`) closes the gap that the live book's
clock (`deploy/live_money.Clock`) was a thread inside the API process with
nothing watching it. The clock now writes `live_money/heartbeat.json` on every
tick. The dead-man switch runs in the kill-switch process, with its own
`.env.killswitch` and no broker key, reads that file and `deploy.json`, and
during market hours on a session the book is armed for trips the kill switch
when the heartbeat is two minutes old, once per session, with a Telegram
message. It cannot square off: the process that could is the one that went
quiet (S-019). The message says to square off by hand and the broker's 15:12
auto square-off stays the last line until broker-side stops land (#125).

**Containers.** `Dockerfile` builds one Python image; `docker-compose.yml`
starts it as `api`, `scheduler` and `killswitch`, plus `web` from
`web/Dockerfile`. The repository is bind-mounted at `/app` so the research
autopilot's commits land in the checkout, and data lives in a named volume
through `EULERLAB_DATA_DIR=/data` (ADR-163). `docker compose up -d` on a VPS
is the whole deployment; `make` on the Mac is unchanged. What is not there
yet: Postgres (#114) and anything per-user (#113).

## Kite login from the Instruments page

India's minute bars need a Kite token minted the same day. `api/kite_routes.py`
gives the page the two ends of a login Zerodha insists on hosting itself:
`GET /api/kite/status` (the link to Zerodha's login page, and whether today's
token is held) and `POST /api/kite/login` (the address Zerodha redirected to,
pasted back, exchanged by `broker.kite_session` exactly as `make kite-login`
does). `GET /api/kite/callback` does the exchange without the paste when the
Kite app's redirect URL is `http://localhost:3000/api/kite/callback`. No route
returns the token, the key or the secret.

"India minute bars" is the last feed step (`daily_feed._india_minute`) and the
row's own Update button. Without a token minted today it reports "skipped" and
passes.

## FYERS login from the Instruments page

The Instruments page also has a FYERS login card. `GET /api/fyers/status`
reports whether today's access token is held and creates a short-lived login
state. The user opens FYERS' hosted sign-in page, copies its final redirect
address, and submits it to `POST /api/fyers/login`. The route checks the
one-time state before `exchange_auth_code` exchanges the code. `GET
/api/fyers/callback` supports a registered local callback URL. The app secret
and access token never go to the browser; the token is stored in the ignored
`.env`, with expiry metadata in `data/cache/fyers_session.json`. The login card
is in `web/components/terminal/FyersLogin.tsx` beside the Kite card.

## Backtest results and the bucket

`cloud_results.mirror` pulls then pushes `data/workspaces/<id>/results/*.jsonl`.
A file is "the same" when its MD5 equals the bucket listing's ETag
(`S3ObjectStore.list_md5`); only files that differ are downloaded or uploaded,
and the bucket is listed once. A store that cannot give hashes is never trusted
to say two files match. `make results-pull` downloads and merges everything.
`make results-dedupe` removes rows identical but for the time written: it
pulls everything, drops the repeats, then pushes without pulling again, since
a mirror would merge the bucket's repeats straight back.

## Company pages (ADR-065)

`/terminal/company/<SYMBOL>` shows what is held about one company. Tiles on
the market map link to it, and the page has its own search. The side column
(price, vitals, classification, not held) is always shown; the main column has
four tabs kept in the address as `?view=`: `overview` (fair value or price
chart, key metrics, earnings bars), `financials` (the six statements),
`peers` and `news`. Notes and caveats open from (i) buttons (ADR-102).

**Sources.** `GET /api/company/{symbol}` reads the newest file under
`data/landing/fundamentals/<SYMBOL>/` through `landing_reader`, so a pruned
file is fetched from the bucket. `features/company_page.build` turns it into
the header ratios, sector levels, index membership and six tables (quarterly
results, profit and loss, balance sheet, cash flow, ratios, shareholding).
The route adds five years of adjusted closes from the price panel and the
newest headlines tagged with the symbol in `data/landing/news/equity/`.
`GET /api/companies?q=` searches the digest by symbol or name.

**Units.** Statement figures are ₹ crore as the source prints them; prices and
per-share figures are ₹; market cap is ₹.

**Computed, not read.** Debt to equity = borrowings / (equity capital +
reserves). Net and operating margin = net profit or operating profit / sales,
latest year. Trailing EPS = sum of the last four quarters, only when all four
exist. Growth = this period / the earlier one − 1, and blank when the earlier
one is zero or a loss. Quarter growth compares with the same quarter a year
before. Industry median P/E = median over companies in the same industry with
positive earnings, blank below three. 52-week high and low are of adjusted
closes, not intraday prices.

**News.** Only headlines that pass `ingest.news.strong_match` for this company
are shown. The archive's own tag is loose: every result of a search for a
symbol carries that symbol.

**Not held, and said so on the page.** Analyst ratings, price targets, forward
estimates, a discounted cash flow, the company description, chief executive,
employees and listing date.

### Fair-value estimates

The company endpoint also assembles an internal residual-income estimate from
the held book value per share, trailing EPS, peer ratios, adjusted daily prices,
the IIMA Indian factor files and the latest held India 10-year yield. Daily
factor betas use up to five years of observations and are shrunk toward neutral
priors. The market ERP uses the roadmap's 7.78% IIMB estimate; IIMA's full
monthly history supplies SMB/HML premia. Cost of equity is bounded to 10%-16%.
The headline composite equally weights the available
residual-income and peer-multiple estimates; banks/NBFCs use P/B as their
multiple check. These first peer checks are not adjusted for growth or ROE.

The API writes each distinct result to `data/derived/fair_value/<SYMBOL>/` as
an immutable JSON snapshot containing model version, input paths, factor hashes,
assumptions, sensitivity values and warnings. Results are low confidence until
analyst forecasts and point-in-time filing vintages are held. The IIMA factor
series currently ends in December 2025; its page may revise history between
releases. The UI names these constraints and shows both source dates.

## The assistant (ADR-064)

A floating button on every screen (`web/components/Assistant.tsx`, mounted in
`app/layout.tsx`) opens a chat about the operator's own data.

**Path of one question.** Browser → `POST /api/assistant/chat` →
`assistant/chat.ask` → the provider named `assistant` in `config/llm.yaml`
(OpenRouter; the model is picked from its live free zero-retention list, ADR-080). The model is sent the conversation and a list of tools. It replies
either with an answer or with tool calls; `assistant/tools.call` runs each and
the text goes back. At most `MAX_ROUNDS` (6) requests per question (a caller
may pass fewer, and only some tools); the last has no tools, so it must
answer, and it gets every tool result as one plain message rather than the
tool-call thread, because gpt-oss-120b kept calling tools from that thread
(research 143).

**Pacing (ADR-125).** Every request re-sends the whole thread, so a tool loop
grows fast. For a provider with `tokens_per_minute` in `config/llm.yaml`
(Groq: 8,000), `chat.pace` guesses each request's tokens (JSON characters / 4,
A-095) and waits only as long as the allowance needs to refill, at the limit's
rate per second, never more than a minute. After each reply it takes Groq's
own `x-ratelimit-remaining-tokens`, which also covers other processes. A 400
`output_parse_failed` is sent once more (A-096).

**What the model can read.** Only `tools.TOOLS`, each capped at 3,500
characters: deployments, positions, orders, next rebalance, data coverage,
strategies, stored results, study outputs, one company's fundamentals, documents (`docs/`, `hypotheses/`,
`research/`, `STATE.md`, `TASKS.md`, `README.md`), and daily prices. Long
series are replaced by a count. No tool writes, trades, runs a backtest or
opens `data/` as a file path.

**Three locks before anything is sent.** The host must be in `ALLOWED_HOSTS`.
A hosted provider needs https and a key. Zero retention is added to every OpenRouter request by `chat.ROUTING` (a model with no such endpoint fails with 404); Groq needs `EULERLAB_ASSISTANT_ZDR=1` instead, because there it is an account setting. The
request body passes through `redact.scrub`, which removes every `.env` value
of six characters or more.

**Choosing a model.** The panel's Model list is every provider in
`config/llm.yaml` (`chat.choices`). A pick travels with the question and passes
the same three locks as the default; one that fails a lock is listed greyed
out with the reason. The pick is kept in the browser.

**What the operator sees.** The host and model in the header, and under each
answer the tools that were sent with their sizes. `GET /api/assistant/status`
gives the reason when it is off and never calls the provider.


## Five intraday microstructure rules (research 133)

`intraday/microstructure_five.py` contains five fixed hypotheses. The first
four need order, trade, or book events; candle volume is never used as a proxy
for signed flow or displayed depth. The fifth rule is implementable from
approved expired single-stock-futures minute candles and archived cash minute
candles. `intraday/futures_cash_backtest.py` discovers contracts, preserves
raw FYERS JSON immutably, maps the cash ticker through the dated instrument
master, and uses an internal contract ID derived from issuer ID and expiry.
Each fetch attempt mirrors the raw tree to `nse/fyers_expired_fo/`, including
responses landed before the daily request cap stops a run. The normalized bars
and result are mirrored to `nse/derived/microstructure_five/micro-05/`. Uploads
verify B2's stored SHA-256 metadata; `make microstructure-five-b2` retries both
mirrors without calling FYERS again.

For each dated contract, the fifth rule calculates close-to-close returns
within each session, then selects the nearest expiry at each minute. It
compares each futures return with the next cash-minute return over the
strictly prior 60 cash sessions and requires at least 500 paired observations
and positive correlation. A futures move of at least 5 bp triggers an entry at
the next cash-minute open; exit is the first cash close at or after five
minutes. Positions for one share cannot overlap. The cash replay charges 2 bp
slippage per side and the date-specific NSE intraday fee schedule. This is a
single fixed-rule research run, not the platform's promotion gate or a live
deployment approval.
## The agent network (ADR-085)

Eight agents on one runtime, `src/eulerlab/agents/`. Each is a YAML file in
`config/agents/` (job, worker module, schedule, daily model budget, what it
may never do) and a worker with one `run(ctx)` function.

```
brief (AI page, make agent-brief, Telegram instruct) ─┐
definition + operator switches (narrow only) ─────┤
                                                  ▼
                       runtime.run ── counted model (assistant locks: approved hosts, ZDR)
                                  │
            data/agents/<agent>/<run>/output.json  +  one line in the hash-chained log
                                  │
                 items that need you ──► inbox ──► approve / dismiss (a record only)
```

| Agent | Reads | Hands on |
|---|---|---|
| data | data quality grades, coverage, feed timings, launchd results | alerts, rerun proposals, answers to data requests |
| knowledge | the knowledge index (papers, cards, notes, decisions, runbooks, grades, Quantpedia, the metrics library, the glossary), through 10 of the assistant's tools; at most 4 requests a question plus 2 for its retry (ADR-125) | answers with sources |
| knowledge_keeper | held data for normals; SEBI, RBI and NSE circular feeds; the metrics library; `docs/ASSUMPTIONS.md` | refreshed normals; notices linked to pages; gaps; drafted page updates for approval |
| market_brief | the running API's market context, world prices, the economic calendar, NSE reports (ban list, deals, IPOs), board-meeting intimations, the books | a pre-open brief or after-close note as data (ADR-105); Telegram in eight lines |
| research | the paper agent's drafts, Quantpedia leads, the cards already tried | ranked drafts, data requests, leads; a summary counting papers read, drafted, not a trading idea, failed and skipped, and a note per rejected paper with why |
| skeptic | a stored backtest's equity curve | attacks: best year, best days, stress windows (A-067), t-stat, costs |
| engineering | the branch's changed files | review findings: operator-owned files, missing docs or tests, boundary breaks |
| portfolio | promoted strategies, deployed books | inverse-volatility weights (capped), drift, retirement proposals |
| operations | step timings against deadlines, contract notes, deployment halts | latency and failure alerts |

**What no agent can do.** `agents/boundaries.py` reads every agent module's
imports and a test fails on the order path, the gate, the trial ledger's
writer, the validation battery, `env`, the deployment runners or `subprocess`.
Reruns go through `agents/jobs.py`, an allowlist of the feed's own idempotent
steps. A brief is text; it cannot raise a budget or switch off a check.

**Budgets.** `log.requests_on(agent, IST day)` sums the model requests of the
day's runs; a run that reaches the budget stops with `over_budget`.

**Memory.** The market brief reads market context over HTTP from the running
API rather than loading a second copy of the 1.85 GB panel.

**A morning note, built as data (ADR-105).** `market_brief.build_brief` saves
the brief as `data.brief` in the order research 134 found traders read:
- headline and tone;
- after the close, this morning's read against the close (`brief_content.review`);
- the three things that matter, from `brief_content.matters` (A-086). Each
  candidate signal is scored by how far its percentile sits from 50 against
  its own history: VIX, breadth, FII futures, FII 5-day cash, valuation (halved),
  the put-call ratio change, the large/small-cap gap, and the trend. Items
  under 25 are dropped. Each carries a fact with its number against normal,
  a rule-written meaning and its metrics page;
- what history says (ADR-109, `agents/history_says.py`): past days since 2015
  whose three fixed conditions in `config/history_setup.yaml` match today's,
  and Nifty's median, share up and worst 10% over the next 1, 5 and 20
  sessions, with matching days and episodes; under 30 days, no numbers.
  Conditions use closes up to the day only. Each running book then gets its
  stored backtest's return on the session after each matching day;
- levels and if-then conditions;
- coming up: expiry, the F&O ban list marked for held names, IPOs open, results due
  from `ingest/board_meetings` (NSE's daily intimations, built forward from
  2026-10-31), and economic releases within two days, each with its time;
- what in the books needs the operator: within 75% of the reduce-only level,
  a holding in the ban, a rebalance due, warnings;
- underneath: sectors, highs and lows by name, delivery, deals, FII/DII runs;
- the scorecard, the analyst note and the detail.

`/api/agents/market_brief/latest` returns it, and `MarketBriefView.tsx` draws it.
`brief_content.telegram` sends at most eight lines. Pre-open runs before
15:30 IST, after-close from 15:30. On a weekend or a day in NSE's holiday
list (`make holidays`, `ingest/holidays.is_session`) it is a markets-closed note
(mode `weekend`): the last session's read under a "Markets closed today" headline,
the week in review (`brief_content.week`) and a seven-day look-ahead. Every
closed-day run writes and shows the note; Telegram gets it once per break (a
run whose data date matches the last note's does not resend it). "Open the
brief" on the agent card opens `#agents/brief`, the AI tab's Market brief view.

### The next-session forecast (ADR-133, research 147)

`forecast/next_session.build` runs inside every brief. From Nifty 50's daily
bars and India VIX (index history, read up to the run's `as_of` by
`knowledge_time`; never minute data, so never the holdout), FII cash
(`fii_dii_cash.rows`) and SPY's closes (US panel), it builds one row per
session with what was known at that close and what followed on the next:

- **Range.** Weighted least squares of the next session's log(log(high/low))
  on today's, the last five and the last 22 sessions' values and log VIX
  (Corsi's cascade on Parkinson's range). The forecast range is
  exp(fit + residual variance / 2). VIX's own range is
  VIX/100/sqrt(252) x sqrt(8/pi).
- **Close band.** z = next log return / exp(fitted log range); the band is
  the close times exp(z at the 10th and 90th weighted percentiles x the
  forecast scale).
- **Odds.** Ridge logistic regressions (IRLS, intercept unpenalised,
  features standardised) of "close above today's" and "open above today's"
  on the last session's and five sessions' log moves, VIX's log change and
  the distance from the 200-day average; then a second stage on FII net
  over five sessions and the US session's log return, fitted with the first
  stage's logit as an offset where both are known (at least 120 sessions).
  Each feature's reason is the probability with it minus without it.
  Expected open: WLS of the gap on the US session.
- **Weights.** Session j of n weighs 0.5^((n-1-j)/500).
- **US session.** The last SPY session after India's last close and before
  the target; 0 when the US was shut in between; when the panel does not
  reach it, the live S&P 500 change if read between 02:30 and 09:15 IST.

**Scoring.** `record` appends a forecast made before 09:15 IST on its target
day, unless it repeats the last one for that day. `live_scores` takes the last
such forecast per session and scores it once the bar is held: Brier for each
odds and for the base rate, close inside the band, |log(actual / forecast)|
for the range and for VIX's. `check` repeats this walk-forward over the last
500 sessions, refitting every 20 on rows whose outcome is known by then.
`trust` uses the live card from 20 scored sessions, the check before; if the
model's Brier is above the base rate's, the brief shows the base rate and
says so, and below 1% skill it says "close to a coin flip".

The brief carries `story` (the last session in words: gap, open-to-close,
range against the 20-session median, where it closed in its range, VIX
against the move, FII that day), `forecast` (titled sections: the forecast
with reasons, scenarios, the record) and, in the review, the last scored
forecast against what happened. Each "what matters" item also carries `why`
(how it bears on the next session) and `watch`. Telegram's range line becomes
the forecast's range, band and odds. A chain whose expiry is on or before the
last close (`trader_read.expired`) is left out of levels, the put-call item and
the calendar.

### News, its tone and possible impact; crash risk (ADR-134, research 148)

Every brief first calls `ingest/market_news.refresh`: ten fixed searches from
`config/market_news.yaml` against Currents API (`CURRENT_NEWS_API`), from 30
days back on the first run (in windows under 7 days, starting an hour inside
the 30-day limit) and from six hours before the newest story after that.
A search with no window answering falls back to Google News RSS (titles only).
Stories land in `data/landing/news/market/<month>.jsonl.gz` via `news._merge`
(first `knowledge_time` wins; searches that found a story unioned into
`symbols`) and in `data/derived/market_news.jsonl`, with `matched` (a whole
word from `relevant`, none from `ignore`) and, once, `tone`.

Tone (`forecast/news_tone.scorer`): the pinned distilroberta financial-news
model on "title. description", truncated to 128 tokens; score = P(positive) −
P(negative). `summary` gives the mean over relevant stories of the last 24
hours known at `as_of`, counts past ±0.3, the mean by theme, and its percentile
against each of the last 30 days' means (days with three stories or more; from
ten such days). `to_judge` drops market recaps (`RECAP`), takes one story per
six-word stem, and draws in turn from geopolitics, policy, global, commodities,
currency and the Indian market, strongest tone first, up to 12. One model
request (`QUESTION`) returns a JSON line per story; `parse_impact` keeps a line
only if its story number exists and is unused, its direction and severity are
from the fixed words, and every figure in its "why" appears in the story.
High severity and "down" is a shock.

`next_session.tail_risk` sorts every session since 2016 by VIX's percentile
against its previous 251 closes (below 30, 30–70, 70 and above) and gives the
share of next sessions down 2% and 3% in today's band and overall, and the
worst. The check card adds `below_band`. The brief's last sections are "News
and possible impact" and "Crash risk"; Telegram gets the 24-hour tone and the
first shock. Neither news nor tone changes the forecast.

### News rules, NewsData and stock tone (ADR-135, research 149)

**Rules.** `news_rules.match(text, rules)` returns the active rule with the
most `when` patterns that all match (whole words, any case) and whose `unless`
patterns do not, seeds before learned on a tie. `corrected(tone, rule)` =
sign(rule) × max(|tone|, 0.5). The brief's summary adds the mean of corrected
scores; stock tone uses corrected scores throughout.

**Learning.** After each judgement, `record` appends every judged story not
yet logged (title, tone, NewsData's score, the judged direction, the rule that
fitted). `learn` rebuilds from the whole log: a story fitted by an active seed
counts for or against that seed; any other story judged up or down counts
toward each (subject, movement) pair of `learn` groups it contains. A pair's
direction is the majority; active when agreeing ≥ 3 and against < 2, off when
against ≥ 2, proposed otherwise. `update` writes the rules and seed evidence
and returns what switched. A seed is contested when against ≥ 2 and against >
for. `agreement` gives, for the last 300 judged stories, how often each score's
sign (|score| ≥ 0.3) matched the judged direction. With no judgement this run,
`rule_impacts` lists what the rules say about the stories that would have been
judged.

**NewsData.** Each search also calls `/api/1/latest` (`q`, `country`, 10
results); `sentiment_stats` becomes `newsdata_tone.score` = (positive −
negative) / 100. Google News results are capped at `page_size` so a day's count
does not depend on which source answered.

**Stock tone.** `stock_tone.build` reads two months of `news/equity` archives,
keeps headlines from the last seven days that name their stock
(`news.strong_match`) and are not quote pages, scores each guid once
(`stock_news_scores.jsonl`), corrects with the rules, and writes per stock the
count, mean, positives, negatives and up to 30 headlines
(`stock_news_tone.json`). `market_news.main` and every brief rebuild it. The
company page adds `news_tone` and each listed headline's tone and rule.

**The Trader's read (ADR-100).** The brief opens with an answer, not a list.
`agents/trader_read.py` turns the gathered inputs into, in this order: a bottom
line; a scorecard of seven rows (trend, breadth, volatility, FII futures, cash
flows, valuation, options), each with its value, what is normal and a word
(supportive, neutral, weak, missing) from `config/trader_read.yaml`; today's
map (last Nifty close, its 20/50/200-day averages, a one-day range of
close × VIX / 100 / √252, the straddle range and max pain when the option data
is no more than three days old); what would change the read, as the numbers at
which a word flips; and each paper book's day, drawdown from its peak and
share invested. The bottom line counts the words (Risk-off when weak exceeds
supportive by two or more, Mixed otherwise) and names a large/small-cap gap
over three points. The model, when it has budget, answers three fixed
questions under the read and passes the grounding check. Telegram gets the
read only, and only when all seven signals are held: an incomplete read starts
"Incomplete: N of 7 signals missing (names)", and Telegram gets one line naming
them instead (ADR-101); the assistant's `market_read` tool returns it, and its prompt tells
it to answer market questions in the same order.

**Workbench.** The AI tab opens on **Live**: a card per agent with its state
(working, done, failed, stopped, never run), the step it is on, its last few
steps and today's model requests, beside a feed of every agent's steps. Then
the inbox, the org chart and calendar (ADR-123), agents and briefs (switch,
budget, brief, run), ask the knowledge agent, research and skeptic runs, the market brief, data quality and the
agents' log. The trade desk is on Live & Risk only.

### The agent company (ADR-123)

The agents are organised as a company. You are the CEO; three departments each
have a head (a manager); every agent belongs to one department. The gate and the
mandate sit outside the chart and answer only to you.

```
you (CEO) ──┬── Head of Research ──────────── research, lab, skeptic, knowledge, knowledge_keeper
            ├── Head of Data and Platform ─── data, engineering, operations
            └── Head of Portfolio and Risk ── portfolio, market_brief
gate and mandate: outside the chart
```

| File | Holds |
|---|---|
| `config/org.yaml` | the CEO's name, each department's id, title and head, and `outside` (the gate) |
| `config/agents/head_<dept>.yaml` | each head as an agent: `reports_to: ceo`, worker `workers.manager`, `options.department`, `provider: groq` (ADR-124) |
| `config/agents/<name>.yaml` | `reports_to`: the agent's department; `duties` (its everyday work) and `can_do` (the task kinds a head may give it) |
| `config/company.yaml` | the company goal and each department's goals: text, how it is measured, `proposed`, `approved` or `retired` |

`agents/org.py` loads both files and `problems()` names what is wrong: an agent
with no department or an unknown one, an agent reporting to the gate, the gate
inside a department, a head with no definition or one that does not report to
`ceo`, run the manager worker and name its department, an agent reporting to
`ceo` that heads nothing, an empty department, goals for a department that
does not exist. The depth is fixed (agent, head, CEO), so a
loop or a second manager cannot be written. `tests/test_agent_org.py` fails if
the committed files have any problem.

**The calendar.** `agents/calendar.py` places each job of
`tools/schedule_daily.JOBS` on the days its `weekdays` allow, at its hour and
minute in IST (A-092). Which agents a job runs is read from its Makefile recipe
(`eulerlab.agents.runtime <name>` lines, or `make agent NAME=<name>`), so the
calendar shows what launchd really starts. Each agent's saved runs
(`output.json`) are matched to slots:

| Mark | Meaning |
|---|---|
| ran | every agent in the job has a run from 10 minutes before the slot until its next slot that day (launchd runs a slept-through job on wake) |
| some ran | some agents have one |
| due | none yet, less than 3 hours after the slot |
| missed | none, 3 hours or more after the slot |
| upcoming | the slot is later than now |
| data job | a job with no agent (`daily`, `india-live`, ...); its result is not read here |

A run that matched no slot (the Run button, the after-close brief that `make
daily` rewrites) shows as run by hand. `GET /api/agents/org` and `GET
/api/agents/calendar?start=YYYY-MM-DD&days=7` serve them; the AI tab's Org chart
and Calendar views draw them.

### Tasks, managers and daily plans (ADR-124)

```
you ── POST /api/agents/tasks ──▶ task (owner = a head, open)
        head run: check finished ─▶ roll up ─▶ split new (Groq, else rules) ─▶ plan the day
        work runner: hand-offs ─▶ run each auto task's agent ─▶ head's checklist ─▶ roll up
you ◀── passed up and closed at once (ADR-160) ── send it back if it is wrong
```

**A task** (`agents/tasks.py`) is the fold of its events in the append-only
`data/agents/tasks.jsonl`; each event is also a `task` entry in the
hash-chained agent log. States: open (a head's, to split), assigned, doing,
review (finished, to check), done, blocked (needs you), closed, cancelled.
`assisted` (AI help fixed it) moves a blocked task back to assigned.
`ALLOWED` refuses an event that does not fit the state, and a task is sent
back at most `MAX_RETURNS = 2` times. `reopen` cancels a parent's unfinished
subtasks so its head splits it afresh; `children` returns only the subtasks
made since the last reopen.

**A skill** (`spec.Skill`, an agent's `can_do`) names a task kind, the worker
argument the task's value fills (`arg`, optional `choices`), `fixed`
arguments, `auto` (may the runner start it unattended?) and `words` for the
fallback. A task runs the agent once with `fixed`, `{arg: value}` and
`task=<id>`. Not `auto`: the lab's `test_card` (spends trials, terminal-only)
and engineering's `fix_code` and `review_branch` (paid model, writes a branch).

**A head's run** (`workers/manager.py`, `make agents-work`, and inside
`agents-preopen` and `agents-ideas`):

1. *Check* each `review` task of its department against `CHECKLIST`: the run
   finished ok, wrote a summary, and the doctor found nothing in it. Pass:
   done. Fail: sent back, then blocked after two. A refused or switched-off
   run, or a failed run whose summary starts `Refused`, is blocked at once (a
   retry would fail the same way). Over budget: assigned again.
2. *Roll up*: a parent whose current subtasks are all settled with one done is
   passed up with their summaries and closed in the same step (ADR-160: the
   checklist already passed, so accepting it is not your decision); one with a
   blocked subtask is blocked.
3. *Split* each open task. Groq is asked first with the roster (agent, kind,
   what, argument) and must answer JSON; `fit` keeps only subtasks naming an
   agent on the team and one of its own kinds, at most `max_subtasks`. If
   Groq has no budget, fails, answers badly or names only agents and kinds off
   the roster, `by_rules` picks the skill whose `words` the task uses most
   (A-093). If Groq read the roster and said nothing fits, the task is blocked
   with its reason and a list of what the team can do; the rules do not
   override it. The parent records `planned_by: model` or `rules`.
4. *Unstick* each blocked agent task once (`tasks.MAX_ASSISTS = 1`), or
   again when you press Ask AI for help (a `help_asked` event). Groq gets
   the roster, the task, why it is blocked and the agent's last run (summary,
   last notes, item titles, inside `<untrusted>`), and answers `retry` (same
   agent and kind, a corrected value), `reassign` (another agent and kind on
   the roster) or `needs_ceo`. A fix that fits the roster and changes
   something is an `assisted` event: the task is assigned again with its
   send-backs reset. Anything else is a diagnosis note for you; the task stays
   blocked. Without Groq nothing is recorded unless you asked, so it is tried
   on the next run. A value sent as JSON is unwrapped. The agents that work by
   fixed rules (data, operations, portfolio) get AI help this way, through
   their head.
5. *Plan*: `agents/plans.py` builds each agent's day (duties, today's
   calendar slots with ran/upcoming/due/missed/not run, open tasks due first,
   finished tasks for a head to check) and the head writes it to `plans.json`
   in its run folder. The page computes the same plan live.

**The work runner** (`agents/work.py`) turns hand-offs into tasks with fixed
keys, so a re-run adds nothing: the doctor's code queue becomes `fix_code` for
engineering (done when the file leaves the queue), and the doctor's
`data_refused` lines and the research agent's data requests become
`check_dataset` for data (HISTORY #64). It then runs every assigned task due
today or earlier whose skill is `auto` and whose agent is on and not
terminal-only, and has its head check the result.

**Capabilities** (`agents/capabilities.py`, `make agents-capabilities`,
`GET /api/agents/capabilities`) check by reading: every agent lists duties and
skills; each skill's argument and fixed arguments are read by the worker's
source (`ctx.args.get("<name>")`); an `auto` skill's agent is not
terminal-only; each skill has fallback words; each head has a model budget; every agent's head can give it AI help when
it is stuck; each department has a skill the runner may start; and every doctor problem
kind has an owner (`DOCTOR_OWNERS`). A test fails on any gap not listed in
`KNOWN_GAPS` (empty). It cannot see a model that fails at run time (research 143).

**The page.** The Org chart view is a family tree (`web/components/terminal/OrgTree.tsx`):
you, the gate beside you, the three heads, and their agents, each with today's
runs and open and blocked counts. Clicking a person shows their job, duties,
today's plan, the skills they can be given (marked "waits for you" when not
`auto`), their tasks with every event, what they can never do, and their
capability checks. Your panel has the task form, what needs you, your tasks
as trees of subtasks, the checklist and the capability summary. Your buttons:
run a waiting task, ask AI for help on a blocked one, retry it, send back a
finished or closed one, cancel. Only major changes wait for you (ADR-160):
merging code, money, buying data, gate runs and trial-spending tests; engineering's
`fix_code` and `review_branch` run as `auto`, and notices with nothing to decide
(research drafts, failed fixes) carry no approve button. Giving a task wakes its head at once
(`agent_routes._wake`: the head's run, then that department's due tasks), on
the API's single agent worker.

**Groq's rate limit.** Requests are paced to it (ADR-125, above), and
`assistant/chat._post` waits out a 429's
`retry-after` once when it is 20 seconds or less (research 142, A-094). The
doctor treats a failed run whose summary starts `ModelUnavailable`,
`Refused` or `BudgetSpent` as `model_down`, not as a code error.

### The knowledge keeper (ADR-104)

`agents/workers/knowledge_keeper.py` with `metrics_library/` keeps
`docs/METRICS/` current. **Daily** (`make agents-close`):
`metrics_library.normals` recomputes each market metric's 5/25/50/75/95th
percentiles over a named window into `data/derived/metric_normals.json`
(event and knowledge time). The assistant's `explain_metric` tool appends
them to the page it returns. `metrics_library.regwatch` lands the SEBI, RBI
and NSE circular RSS feeds once per IST day under `data/landing/regwatch/`
and appends unseen items to `data/derived/regwatch_items.jsonl`. Each item
carries its own date as event time and the landing time as knowledge time.
The first run is marked `baseline` and never reported. A later item whose
title matches a topic in `config/knowledge_sources.yaml` (whole words,
routine titles skipped) becomes an inbox lead naming the pages it may change.
A feed that fails or stops parsing is an alert.

**Weekly** (`mode=weekly`, `make agents-weekly`) adds four checks:
- assumptions past their recheck date;
- pages whose written normals are older than `stale_days` (90);
- market-context sections with no page mapped;
- `explain_metric` lookups that found no page (`data/derived/metric_misses.jsonl`).

It then drafts up to `max_drafts` (3) updated pages from the page plus that
week's linked notices or live normals. A draft with any figure not in that
material is dropped (ADR-088). A kept draft waits in the inbox, and
`make metrics-accept DRAFT=...` copies it over its page; it refuses any
path outside `docs/METRICS/`. Nothing else writes to `docs/`.

**The Market Handbook.** `tools/render_metrics_handbook.py` (`make handbook`)
renders every page, `HOW_TO_ANSWER.md` and the open operator tasks from
`TASKS.md` into one searchable page, `web/public/handbook.html`. The
workbench serves it at `/handbook.html`. It is generated and gitignored,
like `architecture.html`, and rebuilt by `make ui` and after the keeper's
daily run, so it shows accepted drafts the next day.

### Agents on the page they serve (ADR-094)

Each page shows its own agents in a strip under the heading
(`AgentStrip.tsx`, `PAGE_AGENTS`):

| Page | Agents |
|---|---|
| Dashboard | market brief, with the latest brief shown in the strip |
| Strategies | idea lab, skeptic, portfolio |
| Live & Risk | operations, portfolio |
| Data, Instruments | data |
| Research | research, knowledge |

The strip reads `/api/agents/activity` and `/api/agents/inbox`. It polls every
60 s, or every 15 s while one of its agents runs; the AI tab's live view every
30 s, or 5 s while an agent runs. Neither asks while the browser tab is hidden,
and both ask once when it is shown again (`web/lib/poll.ts`, T-4373). Run now posts to
`/api/agents/{name}/run`. The AI tab stays the control room: the inbox, every
agent live, Ask, settings and the log. Engineering shows only there.

A page with more than one agent (Strategies, Live & Risk, Research) shows each
as a small tile: orb, name, status, when it last ran and its inbox count.
Picking a tile opens that agent's full card across the page width; picking it
again closes it (ADR-110). A page with one agent shows its card directly.

Each card says what the last run found, not only how many (T-4212). The
activity route carries `findings`: up to 12 of the run's items, critical first,
then warnings, alerts before findings, each with its explanation and the
command that fixes it; `findings_total` is the full count. The card shows the
worst three and expands to the rest.

- **Skeptic.** A picker lists every strategy with a stored report
  (`GET /api/agents/skeptic/targets`). Run with a strategy, it gives that
  result's full review. Run with "all", or with nothing named, it runs the
  numbers-only attacks on every stored result and lists them worst first. That
  spends no model request and no trial, because it only reads reports already
  stored.
- **Idea lab.** It runs from the terminal (`cli_only`) because it loads the
  whole price panel. The card says so, gives its schedule, and has the command
  with a copy button.
- **Data.** The summary reads "N clean (A or B), N usable with a failed check
  (C), N not usable (D)" and names the critical datasets that block backtests.
  Each failed check is said as the problem it is (`CHECK_WORDS`), and the card
  carries the key to the grades.
- **Operations.** The summary names each alert, and a halted book's alert says
  why it halted and that it places no trades while halted.

### What an agent is doing now (ADR-091)

```
runtime.run ── step("Started …") ─┐
worker ── ctx.step(…) / ctx.notes.append(…) ─┤──► data/agents/<agent>/<run>/progress.jsonl
ctx.ask ── "Asking …" / "The model answered" ─┤        {at, kind: start|step|note|model|end, text}
runtime.run ── step("Finished: status · summary") ─┘
                                   │
         GET /api/agents/activity ─┴─► newest run per agent + all steps newest first
```

A run with no `output.json` is *running* while its last step is under 15
minutes old (or the web server started it), and *stopped* after that. Steps
carry no model text, only what the code chose to say.

A run the doctor closed (`data.closed_by == "doctor"`, ADR-113) also shows as
*stopped*, not *failed*: it stopped because the Mac slept or the app closed.
A stopped card's summary says so and gives the newest run that finished ok,
with that run's findings, so a full run is not hidden by a later one that died.

### When a model makes something up (ADR-088)

`agents/grounding.py` checks every number (two digits or more, or with a
point, comma or %), id and file path in an answer against the text the model
was given. A number counts as supported when the evidence holds the same
value at the answer's precision, or the same share as a fraction (12% for 0.12).

| Where | On an unsupported figure |
|---|---|
| Knowledge answer | One retry that names the figures; then "Not held", listing them. The first answer is kept in the output |
| Market brief commentary | Dropped; the brief goes out with data only, and a note says why |
| `make agent-eval` | A figure the operator would have seen switches the agent off until the operator switches it on |

Each output records a fingerprint of the prompts it ran under, so a changed
score can be traced to a prompt change. `make agent-eval` runs weekly in
`agents-weekly`; the skeptic part is free, the knowledge part uses its budget.

### Lessons, the guardian and the feedback desk (ADR-152)

Three loops close the organisation around the agents. None of them uses a model
to decide anything.

```
docs/HISTORY.md, gate/screen findings, guardian trips, operator feedback
        |  lessons.add (append-only, id = hash of source + ref)
        v
data/agents/lessons.jsonl --relevant(agent, prompt)--> Context.ask system prompt
        |                                              (operator first, then the
        |                                               agent's own, then >= 2 shared keywords;
        |                                               at most 6; ids kept on the output)
        +--violations(spec)--> autopilot.accept drops a card that breaks a coded lesson

runtime.run -> doctor.after_run (remedies) -> guardian.after_run (stops)
   protected file changed ......... halt every agent   (data/agents/HALT)
   3 withheld answers in a day .... suspend the agent  (settings: enabled=false)
   3 failed runs in a row ......... hold: told + lesson; it keeps running so fixes can heal it
   ledger entries > weekly allowance  suspend the autopilot
   screened net Sharpe > 3 ........ hold: lesson + Telegram; readiness blocks a pilot
   lift a halt: make agents-resume REASON=...   lift a suspension: the AI tab switch

make feedback TEXT=... / Telegram "feedback ..."
   a rule (never, always, avoid, must ...) -> operator lesson (all agents, or "agent: ...")
   anything else (incl. "goal: ...")        -> task for head_platform / head_portfolio /
                                                head_research by keywords
   every message -> data/agents/feedback.jsonl with where it went
```

The guardian's thresholds are A-125. It reads the autopilot's own gate log as a
file, so nothing the runtime loads reaches the gating code.

### Live-price paper and readiness (ADR-153)

The paper books fill at the official open and close. `deploy/live_shadow.py`
prices the same picks on live Kite quotes without sending anything:

| When (IST) | Command | What |
|---|---|---|
| 22:30 daily | `make live-shadow-evening` | reconcile today's sweeps with the bhavcopy close, then plan the next session |
| 09:16 weekdays | `make live-shadow-open` | quote the candidates; apply the gap condition; rank; record bid, ask, spread |
| 15:10 weekdays | `make live-shadow-close` | quote the picks where an MIS book must exit |

Per trade, in bps, gross of costs, with side s = +1 long or -1 short:

```
backtest   = s * (official_close / official_open - 1) * 1e4
achievable = s * (exit_quote / entry_quote - 1) * 1e4     short: sell at bid, cover at ask
slippage   = backtest - achievable
```

`make readiness` lists, per strategy, the evidence for real money. A strategy is
pilot-ready only when every line holds: an active paper book; live-price
sessions >= the pilot's minimum (10 by default) with mean achievable return
above 12.24 bps of costs; a broker order path proved by one supervised round
trip (`data/oms/kite_proof.json` or `data/oms/angel_proof.json`);
a kill switch trip and reset within 30 days; no guardian hold; the operator's
go (`data/desk/live_go.json`); and a `forward_test.pilot` block in the mandate.
Full size needs the mandate's `forward_test` instead of the pilot block.

**Angel One (ADR-154).** The sweeps use Kite quotes; when Kite has no fresh
token they use Angel One's (`broker/angel_check.quotes`, login by PIN and TOTP,
no person needed) and record `quote_source`. Angel symbols map to tokens by
scrip search, cached in `data/master/angel_nse_tokens.json`. `make angel-readonly`
reads funds, orders, positions, a quote and the MIS list and sends nothing.
`make angel-proof SYMBOL=SBIN CONFIRM=SEND` buys 1 share MIS through
`broker/smartapi.SmartAPIBroker` and sells it back; it refuses without
`CONFIRM=SEND`, with the kill switch tripped, at weekends and outside 09:20–15:00
IST, and writes the proof only when both legs complete.

### Real money from the workbench (ADR-162)

`deploy/live_money.py` runs one card, H-0194, with real orders through Angel
One. The operator enters an amount, a leverage (1x to 5x) and a daily loss cap
on Live & Risk → Deployment and types DEPLOY. That arms **one session**; the
deploy ends after it.

Sizing: exposure = amount x leverage; names = min(10, exposure / ₹5,000),
equal rupees a name. A small amount trades fewer names, never a bigger one.

The API server's clock (`live_money.CLOCK`, every 20 s) does the day:

| When | Step | Fails closed when |
|---|---|---|
| evening, or before 09:20 | watchlist: the liquid 500 of the last session, less ETFs, ASM/GSM, trade-for-trade, under ₹100, or too dear for one share | data or ASM/GSM list missing |
| 09:20-09:35 | Angel quotes; gap = open / previous close - 1; keep \|gap\| >= 3%, no non-administrative NSE filing since 15:30, spread <= 50 bps; largest gap first; MIS market order against the gap | NSE filings or quotes do not answer; kill switch tripped |
| every minute | P&L = fill price vs last price, less estimated costs (S-059); at the loss cap trip the kill switch and close all | — |
| 15:10 | close every position this book holds at the broker; the deploy ends | — |

Entries check the kill switch; exits do not, because closing is what a tripped
switch wants. The broker's position book decides what is open. Client order
ids are `hash(H-0194-live, session, symbol, seq)`; an exit retried takes the
next `seq` for only what is still held. Clearing the switch is not on the
screen: it needs `KILLSWITCH_TOKEN`. Files: `data/live_money/deploy.json` and
`data/live_money/<session>/{plan,open,watch,close,dry_run}.json`, `log.jsonl`.

### The agents' memory in B2 (ADR-128)

`make agents-backup` (`ingest/memory_backup.py`, last step of `make agents-ideas`)
sends what the agents know to the bucket under the storage prefix:

| Local | Bucket key | What |
|---|---|---|
| `data/agents/` | `memory/agents/` | every run's output, the lab's memory, tasks, the hash-chained log, plans |
| `research/agent_drafts/` | `memory/research/agent_drafts/` | drafts and each run's `run.json` |
| `research/papers/` | `memory/research/papers/` | the library, which research adds to daily |
| `data/derived/trials.jsonl` | `derived/trials.jsonl` | the trial ledger (same key as `make sync-derived`) |

A file is sent when its MD5 differs from the bucket's ETag (one listing per
tree), so a rewritten file that shrank is still sent; the raw-data mirror,
which compares sizes, would refuse it. Locks, partial files and the
engineering agent's git worktrees are skipped. Nothing in the bucket is
deleted. `make agents-restore` downloads each tree only into a missing or empty
folder and skips a key that would land outside it (runbook
`agent-memory-restore.md`). The first backup, 2026-11-03: 360 files in about
5 minutes; a second run sent none.

### The idea lab and the agents' trial allowance (ADR-089, ADR-111)

**No weekly limit since 2026-10-31 (ADR-107).** `per_week: null` in
`config/agent_trials.yaml`; a number puts a cap back. Every trial is still logged
before its result is read.

**Research first, then the lab, then engineering, since 2026-11-03 (ADR-128).**
The operator: "order should be research then lab then engineering". Research
picks its own topic (a task's, the brief's, else one a day from `topics` in
`config/agents/research.yaml`); the lab's record reaches it only as memory
(families that failed, features drafts named that the library lacks), never as
a topic. The lab writes no ideas of its own (`max_ideas: 0`, `model_ideas: 0`):
it backtests research drafts, and records a draft it cannot build for a named
signal (`data.unbuildable`), which the work runner run after it hands to
engineering (ADR-127) the same evening. Raising those two options brings back
the lab's own ideas described below. Then `make agents-backup` sends the day's
memory to B2.

```
 17:00 IST  make agents-ideas
   heads, work runner ─► research ─► lab ─► work runner (engineering) ─► agents-backup
```

**Its own ideas and a memory, 2026-11-01 to 2026-11-03 (ADR-111), now off.**

```
 17:00 IST  make agents-ideas
   research ── topic: arg > brief > lab feedback (one topic a day, in turn) > standing topic
      │        prompt carries the lab's lessons; buildable drafts never "wait for data"
      ▼ drafts
   lab ── every untested draft from the last 50 research runs (up to max_cards)
      │ + its own plan for the day (max_ideas, default 30):
      │     flips of signals with t <= -2      ─┐
      │     combinations of two passers         ├ a third of the slots while fresh
      │     window variants (halved, doubled)  ─┘ templates last; all slots after
      │     fresh templates, family by Thompson sampling on Beta(1+pass+2·survive, 1+fail)
      │ + up to model_ideas formulas from the model, parsed by the formula language
      ▼ one card each under research/lab_ideas/<day>/, one configuration, written before testing
   panel read once, cut at the card's holdout
      │
   IC screen per feature (1 trial each) ── fails ─► memory
      │ every feature passes (IC >= 0.02, t >= 2)
   Tier A backtest per configuration (1 trial each) ── skeptic ──► memory
      │
   survivors ─► inbox ─► operator: register, make gate
   memory ─► lessons + feedback (output.data.feedback) ─► tomorrow's research and plan
```

| Piece | Where | What it holds |
|---|---|---|
| Families | `config/idea_families.yaml` | 13 reasons, each with formula templates, windows, rebalance, a paper-search phrase (A-088) |
| Planner | `research/idea_generator.py` | Dedupes by canonical formula; the ten library features count under their own names; seeded by the date |
| Memory | `data/agents/memory/lab_ideas.jsonl` | One line per card tested: family, source, features, IC and t, best robust Sharpe, survived |
| Lessons | `idea_memory.lessons` | Computed rules, each citing experience ids: survivors, families passing, families dead (4 tries, none through), signals worth reversing |
| Feedback | `idea_memory.feedback` | Families working / dead / untried, features drafts lacked, paper topics in order |

Only one lab run tests at a time: it holds `data/agents/lab.running` (taken over after 4 hours).

**Liquidity floor and Nifty (ADR-112).** Every generated card sets `min_turnover`
(Rs 1 crore on the day, `config/idea_families.yaml`); its IC screen applies the
card's lowest floor (`ic.evaluate(min_turnover=)`), so screen and backtest judge
the same stocks. A survivor needs robust Sharpe > 0, no critical skeptic finding,
and a positive Sharpe of its daily return over NIFTYBEES on 250+ shared days.
Planning and lessons read only `idea_memory.usable` experiences: research drafts
and own cards at today's floor. Unbuildable drafts are listed in the feedback and
never take a draft slot.
A family is called dead after 4 cards with none through the screen, and its
search phrase leaves the topic list. The lab stops starting new cards after
`max_minutes` (90); what is left is planned again the next day because it is
not in the memory.

Every trial is written to `data/derived/trials.jsonl` as `agent|<card>|...`
before its result is read, so `budget.searches_run` and the noise bar count it.
`research/agent_trials.py` is the only trial path an agent may import, and only
`workers/lab.py` imports it (test-enforced). The lab reads the whole panel, so
the web page refuses to start it; it runs from `make agent NAME=lab` and
`make agents-ideas`.

### The forward-test stage (ADR-117)

    gate PROMOTE in the ledger (latest gate verdict for the subject)    -> promoted
    + active paper deployment, start >= promotion day (operator starts it) -> forward_testing
    + active live deployment                                             -> live

`forward.stage` derives it; `strategies.fleet` and the deploy preflight read it.
A promoted hypothesis `H-NNNN` deploys to paper as `forward.GatedCard`: its
card's one configuration built by `codegen.build_one`, with the card's
rebalance. The version lock fingerprints the card text and the trading code.
`forward.report` measures each forward deployment from its `state.json` curve:
days, annualised Sharpe, max drawdown, and the ledger's best backtest Sharpe.
`ready_for_live` applies `mandate.yaml` `forward_test:` (`min_days`,
`min_sharpe_ratio_of_backtest`, `max_drawdown`); with no such section it says
"not set". Live preflight also needs a fresh Kite session and a proven adapter;
`make kite-readonly` exercises the adapter's read paths through a client whose
write methods raise.

### An approved survivor goes to the gate (ADR-116)

    Inbox: approve a lab finding ("<card>: N configuration(s) survived")
      -> promote.eligible: agent is lab, survivors >= 1, card exists, every
         configuration has min_turnover > 0, no registered.json beside it
      -> promote.register: hypotheses/H-NNNN.yaml (next free id, configurations
         untouched, status draft); registered.json beside the lab card
      -> python -m eulerlab.validation.run --hypothesis H-NNNN   (own process)
      -> python -m eulerlab.gate_run --hypothesis H-NNNN         (own process, never --read-holdout)
      -> data/agents/promote/H-NNNN.json: the gate's VERDICT line and both outputs

One gate run at a time (`_GATE_POOL`, one worker). `GET /api/agents/promotions`
lists them; the Inbox shows them under Gate runs. Each row also carries
`findings`: every rule the gate printed (`pass`/`KILL`, rule, detail with the
value and the mandate's threshold), parsed back from the gate's own output by
`promote.findings`, so "View more" on a KILL lists what failed and what passed
without recomputing anything. Validation builds a lab card's
strategy with `codegen.build_one`, so a formula feature and its liquidity floor
are validated exactly as the lab tested them.

### The doctor and the engineering fixer (ADR-113)

After every agent run, `runtime.run` calls `agents/doctor.after_run(output)`. It never raises and takes remedies only from `doctor.REMEDIES`:

| Problem | How it is seen | Remedy |
|---|---|---|
| stalled | a run folder (`YYYYMMDDTHHMMSSZ-xxxxxx`) with no `output.json` and no step for 3 hours | write a failed `output.json`, so the card stops saying running |
| suspicious | a lab result with robust Sharpe above 3 or IC t above 10 | flagged in the doctor log; the lab also adds it as a critical finding, so it cannot survive |
| model_down | "no model ideas today" or a refusal in the notes, or a failed run whose summary starts `ModelUnavailable`, `Refused` or `BudgetSpent` | noted; the next run tries again |
| data_refused | a refused run whose summary names grade or data | logged; the work runner makes it a `check_dataset` task for the data agent (ADR-124) |
| code_error | a failed run whose traceback has a `src/eulerlab` frame | queued for engineering under the deepest such frame (`data/agents/doctor/code_queue.jsonl`) |

The runtime keeps the last six traceback frames, so the deepest frame is the one that raised.

`engineering --arg mode=quality` (in `make agents-close`) runs ruff, mypy and pytest over the repository and queues one finding per file. `mode=fix` (and `mode=quality` after the check) takes up to `max_fixes` queued files and hands each to `devtools/fixer.fix`:

    refuse NEVER (gate, mandate, oms, broker, deploy, validation, trials ledger, boundaries, env, devtools, config, .env)
      -> git worktree on agent-fix/<id> from HEAD
      -> Claude Opus: CLAUDE.md + ARCHITECTURE sections naming the file + file + first test importing it + error
         -> JSON {explanation, file, test}
      -> git diff must name only the file and that test
      -> ruff, ruff format --check, mypy (file), pytest (its tests), backtest self-test
      -> red: one retry with the failures; still red: a finding for the operator
      -> green: commit, push the branch, a proposal "fix ready" with `make agent-fix-apply ID=<id>`
      -> worktree removed in every case

The fixer runs only fixed commands with fixed arguments; the model's text is written to files in the worktree, never to a shell. `agents/boundaries.fixer_users` holds the fixer to `engineering.py`.

**Which model (ADR-127).** `options.models` in `config/agents/engineering.yaml`, in order: free Groq, then Claude Opus. A model is skipped when it is unreachable, or when one request (characters / 4) would use more than 80% of its `tokens_per_minute` (`engineering.FIT`). A bug fix carries CLAUDE.md and the module, far past Groq's free 8,000 a minute, so fixes run on Opus; a signal fits. The next model is tried only when the first one's code failed a check. The checks do not change with the model.

### The data agent's routine, the watchdog and the token log (ADR-132)

**The data agent** (`agents/workers/data.py`) runs at 06, 08, 10, 12, 14, 16, 18 and 20 IST (`make schedule JOB=data-watch`, `com.eulerlab.datawatch`) and in the 08:45 and 16:15 agent runs:

    grade every dataset (quality contract)
      -> freshness: today's data before 21:00 IST is "due tonight", not stale
      -> download with the allowed feed steps (`jobs.ALLOWED`, no Kite): stale datasets,
           and from 18:00 IST (`TRY_FROM`, A-014) today's due files too; a row no allowed
           step can update (MCX index bars, Kite only) becomes "Needs you"; without a Kite token
           "India minute bars" fetches from Angel One (`daily_feed.angel_minute_fill`, last two
           complete sessions) into Kite's own stores `kite_minute` and `kite_index_minute`, in Kite's
           file layout and `+0530` timestamps, manifest `"source": "angel_one"`, so backtests read
           them unchanged and Kite does not refetch those days; the card's first
           sentence says what was downloaded and what is still not in
      -> upkeep, under the `feed` lock (skipped while `make daily` holds it):
           upload the landing trees `make daily` uploads, delete local files B2 holds at the same size
           merge-back: each local file that differs from its B2 copy is merged into it
      -> anything still wrong: one Groq request -> rerun one allowed step | task for head_platform | "Needs you"

**Merge-back** (`ingest/merge_back.py`, also `make data-merge-back` at the end of `make daily`): for a `.jsonl.gz` file whose B2 copy has another size, both copies are read; a row is the same row when every field but `knowledge_time` and `receipt_time` matches (A-101) and is kept once with the earliest `knowledge_time`; B2's rows keep their order and rows only the local copy has follow. A merge that adds nothing means the local file was a duplicate: it is deleted. Otherwise the merged file (gzip `mtime=0`) is uploaded, and the local file is deleted only when a listing taken after shows it at the merged size. Other files that differ, and unreadable ones, are reported and kept. At most 4,000 files a run; `data/derived/merge_back.json` holds the last report.

**The token log** (`llm/usage.py`): `chat._post` appends each reply's `usage` (OpenAI `prompt_tokens`/`completion_tokens`, Anthropic `input_tokens`/`output_tokens`) to `data/derived/llm_usage.jsonl` with the agent and run that asked (`usage.asking`, set by `runtime.run`); the assistant panel is `assistant`. `output.json` and the agents' log carry the run's `tokens`.

**The watchdog** (`agents/workers/watchdog.py`, last in `agents-preopen`, `agents-close` and `agents-ideas`; `make agents-watchdog`) reads the last 26 hours:

| Check | Problem when |
|---|---|
| runs | a run failed, was over budget or refused; the last 3 all failed ("stuck") |
| missed | no run within `expect` hours (weekday-only agents get Saturday to Monday 17:00 off) |
| requests | an agent defined without a model asked one; an agent used all its `daily_requests` |
| tokens | an agent over 60,000 a day, an average request over 12,000, all agents over 160,000 (Groq's free 200,000) |
| tasks | blocked, sent back twice, or open past its due day; never a task the watchdog raised (or its steps) and never one only you may start (ADR-159) |

Remedies: re-run once a day an agent in `rerun_ok` (data, operations, portfolio, knowledge_keeper) whose run failed or was missed; never the lab, research or market brief. What is left goes to one Groq request (4 a day), whose answer per problem becomes a task for the agent's head (none while an open watchdog task for that head and problem exists), an alert for the operator, or a note that it will clear.

**Which research cards the lab queues (HISTORY #73).** `lab.candidates` takes research drafts that are not repeats, whose `draft.json` says `card: valid`, and that no earlier lab run found unbuildable with no named signal (`lab.never_buildable`). A card waiting for engineering to code a named signal stays queued, so it is tested once the code is merged. Research's summary counts both: "3 drafted (1 complete)".

**Heads check delivery.** `manager.CHECKLIST` has a fourth item: a `research_topic` run that drafted 0, or a `test_card` run that tested 0 cards, is sent back (research then reads papers it has not judged), and after two returns blocked for AI help. Research marks a card incomplete when a `formula:` feature does not parse or a ranked configuration names no feature (`paper_agent.card_problems`), so the lab is never handed a card no code can fix.

### Coding the signals research cards name (ADR-127)

A research card may name a signal the library lacks (`feature: liquidity_beta`). The lab cannot build it and records it in its output (`data.unbuildable`: card, named features). The work runner (`work.coding_handoffs`) turns each one into a `code_feature` task for engineering when the card was complete when drafted (`draft.json` `card: valid`) and the name is a plain name, one task per signal ever, at most `options.max_features` (2) new a day. The task runs by itself (`auto`), Groq first:

    devtools/fixer.code_feature(name, card)
      -> git worktree on agent-feature/<name>-<id> from HEAD
      -> model: a short prompt (features/base.py, one example feature, the card; fits Groq's free minute)
         -> JSON {explanation, file, test}, or file null: "cannot be built from one stock's own history"
      -> mechanical clean-up, not the model: unwrap a code fence or triple-quoted string,
         typographic dashes and quotes to ASCII, `ruff check --fix`, `ruff format`
      -> only features/coded/<name>.py and tests/test_coded_<name>.py may appear
      -> coded.problems (pure), ruff, format, mypy, pytest (its test + tests/test_coded_features.py), engine self-test
      -> red: one retry with the failures, then the next model, then a finding for you
      -> green: a line in docs/CODED_FEATURES.md, commit (`--no-verify`: the same checks just
         ran; CI runs only on main, ADR-144), push, `gh pr create`
      -> a failed attempt's branch is deleted with its worktree
      -> worktree removed in every case

**Why a coded signal cannot look ahead.** It is a function of one stock's own history, handed to it ending at the decision day. It could only see later data by reading something else, so `features/coded.problems` refuses any module that does not compile, imports outside a short list (`math`, `statistics`, `collections.abc`, `itertools`, `features/base`, the panel row, `robust`; never the library, which imports the coded package), calls `open`, `eval`, `exec` or similar, touches a dunder attribute or keeps `global` state. That check runs at load time in every process (a refused module is never imported, and one that raises on import is skipped, so a bad signal cannot stop the library loading) and in `tests/test_coded_features.py`, which also checks every coded feature returns None on short history, only finite floats otherwise, the same answer twice, and leaves its input unchanged.

**After you merge.** `library.BY_NAME` loads `features/coded` at import (seeds first; a coded name cannot replace one), so codegen, the lab, backtests and validation all see it. The card stays on the lab's list while it cannot be built, so the lab's next run tests it, logging its trials first. A signal that needs other stocks, the market or fundamentals is not coded: the task ends with the model's reason, for you.

## The data quality contract (ADR-086)

`config/data_sources.yaml` registers every dataset. `make data-quality` grades
each one:

| Check | Fails when |
|---|---|
| registered | the dataset is not in the register |
| provenance | publisher, address or licence is missing; `unreviewed` licence warns |
| fingerprint | a landed file has no SHA-256 or no knowledge time |
| sense | duplicates, empty files, calendar gaps (`quality/manifest_checks.py`) |
| quarantine | one of its files is held |
| freshness | reported beside the grade, not in it |

A = all pass; B = warnings only; C = one failure; D = more, or nothing landed.
A derived table takes the worst grade of what it is built from, and a source
that cannot date its values (`point_in_time: false`) is B at best.
Quarantine is an append-only list (`data/quality/quarantine.jsonl`); the raw
file is never moved. The panel build skips held files and holds any file whose
SHA-256 no longer matches its manifest. `make backtest` refuses a price panel
below its minimum grade unless `ALLOW_LOW=1`. Optimisation sweeps are refused
outside the grid written on their card (`research/grid_rule.py`).

## The trade desk and the version lock (ADR-087)

One ticket per active deployment (`desk.py`): sells and buys at the next
rebalance, estimated cost at 0.25% a round trip (A-068), the reason, and
pre-trade checks (kill switch, data grade, version lock, position size, order
rate). A blocked ticket cannot be approved. `deploy/version_lock.py`
fingerprints a strategy's own source on its first run. Paper books whose code
changed trade on with a warning; a live book stops, and also stops unless
that day's ticket is approved. `make relock DEPLOYMENT=... NOTE=...` accepts
reviewed code.

## Quantpedia (research 125)

`make quantpedia-sync` lands Quantpedia's strategy list and up to 50 new
strategy details a run under `data/landing/quantpedia/<day>/`, with a SHA-256
manifest; nothing landed is fetched again. Needs `QUANTPEDIA_USERNAME` and
`QUANTPEDIA_API_KEY` in `.env`. Their Sharpe ratios are their own, shown as
prior evidence only.

## The stock screener (ADR-136, research 150)

**Point-in-time fundamentals.** `fundamentals/annual.build` takes each ticker's
newest screener.in snapshot (consolidated first), keeps the annual rows it
needs (sales, operating and net profit, EPS, payout, equity capital, reserves,
borrowings, total assets, operating cash flow, ROCE) and dates each year
`known_from = fy_end + 90 days` (FY2020: 1 August 2020). Tickers resolve to the
ISIN on their latest panel row. Only changed snapshots are re-read. `known(years,
day)` returns the years with `known_from <= day`.

**Units.** screener.in back-adjusts EPS for later splits and bonuses. A decision
on `day` sees prices adjusted only for actions up to `day`, so per-share values
are multiplied by `units(isin, day)`, the product of the factors of every action
after `day`: earnings yield = EPS × units / close; book yield = (equity capital
+ reserves) / (net profit / EPS) × units / close.

**Signals.** Quality = mean of the cross-sectional rank (−1..+1) of ROE,
operating profit / total assets, −borrowings / equity and payout (a stock needs
half of them). Value = mean rank of earnings and book yield. F-score = 8 of
Piotroski's 9 (ROA > 0, CFO > 0, ΔROA > 0, CFO > profit, Δ(borrowings/assets)
< 0, equity capital not up, Δ operating margin > 0, Δ asset turnover > 0).

**Models** (liquid 250 as of each date; equal weights):

| Id | Rebalance | Rule |
|---|---|---|
| `screen_quality_momentum` | 21 | Better half on quality; top 20 by 252-day return / volatility |
| `screen_value_momentum_quality` | 21 | Top 20 by mean of value, quality and 12-1 momentum ranks |
| `screen_piotroski` | 63 | Cheapest 30% on book yield with F-score ≥ 6; up to 30 |
| `screen_tree_ranker` | 21 | HistGradientBoosting (200 trees, 15 leaves, 0.05, seed 0) fit at each decision on the previous 24 month-ends' 11 features → next-month return rank; top 20 |
| `screen_trend_pullback` | 5 | Close > SMA200, SMA50 > SMA200, RSI(2) < 10 within 10 sessions and no close with RSI(2) > 70 since; 1/10 each |
| `screen_52w_breakout` | 5 | Close ≥ prior 251-session high on volume ≥ 2 × 50-session median, within 20 sessions; 1/10 each |

The tree model needs `scikit-learn` (`research-ml` extra) and holds nothing
without it.

**Today's lists.** `screener.build` builds the view for the panel's last day
with `adjusted_view` (the engine's `_view_history` rule: each row divided by
the factors of actions after it and on or before the day), runs the six and the
five in `config/screener.yaml` through `decide`, and records per liquid stock:
1-month and 12-1 returns, distance to the 52-week high and the 200-day average,
RSI(2), median turnover, quality and value percentiles, F-score, ROE, P/E, P/B,
debt/equity, news tone (ADR-135) and which models pick it. Each list carries its
stored screening run (`screener_models.json`, `india_papers.json`, …).

**History.** `record` appends each model's picks once per `as_of` to
`screener_history.jsonl`. `outcome` measures a selection from the first session
after `as_of` (the engine's fill) for `HOLD` sessions (5 swing, 21 long) or to
the latest close, on today's adjusted view, equal-weighted, against NIFTYBEES
over the same sessions; `track` summarises complete ones: mean excess and the
share beating Nifty. `/api/screener` serves `screener.json`; Workbench →
Screener draws it.

### Blends and the pre-registered choice (ADR-137, research 151)

`screener_models.Blend(name, parts, rebalance_every)` builds each part from
`published.BUILDERS`, lets each decide on the view narrowed to its own lookback
(`decide`), and returns Σ share × weight per stock; its lookback is the longest
part's. Four are declared: `screen_long_blend` (quality momentum 0.7, tree
ranker 0.3; 21 sessions) and three swing blends at 5 sessions: A = Sharpe
momentum (paper setting, `india_sharpe_momentum`) + Weinstein stage 2, B =
52-week breakout + Weinstein, C = all three in thirds. `screener.choose` marks
`main_long` from `config/screener.yaml`, reads each candidate's Sharpe from the
two half-period summaries (`halves`), and marks as chosen the candidate whose
smaller half-Sharpe is largest (ties: fewer parts), only if that exceeds
`robust_floor` (0.5). Lists are ordered main, chosen, new, then the rest. Each
tab of the page opens on its main or chosen list.

### The consensus list (ADR-138, research 152)

`screener_models.Consensus(name, parts, min_votes, rebalance_every)`: `picks(view)`
runs each part on the view narrowed to its lookback and returns its long names;
`votes(view)` counts, per stock, the parts picking it; `target_weights` holds the
stocks with votes ≥ `min_votes`, equally (none: cash). `screen_consensus_3of5`
uses `CONSENSUS_PARTS` (Stocks on the Move, Sharpe momentum paper setting,
Weinstein stage 2, quality momentum, physical momentum), 3 votes, 21 sessions,
and is `main_long` in `config/screener.yaml`. `screener.build` stores, for every
list, each pick's weight, and for a consensus its votes and each part's picks.
The page ranks the main list by votes, then weight, quality percentile and 12-1
momentum, and shows the first 10, 20 or all.
`screener.parts_of` reads both kinds of combined strategy: a `Blend`'s
(strategy, share) pairs and a `Consensus`'s (id, strategy) pairs, each part an
equal vote (the first build read only the first kind and failed on the
consensus, 2026-11-04).

### Top-down screening, likely movers and the brief's stock ideas (research 182)

**Sector tags.** `fundamentals.sectors.build(isin_of)` reads each ticker's newest
screener.in snapshot and keeps its `section == "sector"` rows: `level_1` broad
sector, `level_2` sector (about 40), `level_3` industry, `level_4` basic
industry. It writes `data/derived/sectors.json`, ISIN → tag; `make
fundamentals-annual` builds it with the annual table. Tags are today's, applied
to the past (A-128).

**Ranking.** `backtest.topdown.rank(view, names)`: each named stock's 126-session
return; a sector's and an industry's score is the equal-weighted mean of its
members, counted with 3 or more; an industry with fewer inherits its sector's
score. The top 5 sectors are kept; an industry is strong when its score is above
the median of the industries scored on their own. `Ranking.passes(s)` = in a top
sector and a strong industry.

**Models** (`screener_models`, kinds long/swing): `screen_topdown_sectors` (every
liquid stock in the top 5, a fifth per sector), `screen_topdown_quality_momentum`
(passes, quality ≥ median, top 20 by Sharpe momentum, at most 6 per sector,
`_capped`), `screen_topdown_discount` (passes, positive earnings yield, mean rank
of Sharpe momentum and of earnings yield less its industry median,
`industry_relative`), and `TopSectorsOnly` wrapping the trend pullback and the
52-week breakout (targets kept only in the top 5 sectors, weights unchanged).
`events_daily.DriftMomentum(topdown=True)` ranks only top-sector stocks.
`research.topdown_run` runs each through `api.server._engine_run` (which now
takes `cost_multiplier`) on 2016-2026, each half and at 2x costs, with each
calendar year's return from the equity curve (`make topdown-screen`).

**Likely movers.** `movers.build(view, names, table)`: the reaction session of a
results disclosure is the first session whose close follows it (before 15:30 on
a session day: that day; else the next). Typical results-day move = median
absolute close-to-close return over 3 or more past reactions (`events_daily.
announcements`, 2021-2024, plus the last 90 days from `daily_books.results_times`).
Lists: results due in 7 days among the liquid 250 (`board_meetings.upcoming`)
with that typical move; reactions of 5% or more within 60 sessions, tagged H-0187
(today's) or earnings drift (positive, 2-60 sessions); and today's close at a new
52-week high on twice the 50-session median volume. `drift_picks` is
`india_drift_momentum_combo` on today's view (reaction 2-60 sessions old beating
NIFTYBEES over two days, Clenow's filter, 15 best by his score). `screener.build` stores
`topdown` (sectors, industries in the top sectors, each stock's sector, industry
and flags) and `movers` in `screener.json`.

**The brief.** `market_brief` reads `screener.json`; `brief_content.ideas` turns
it into sections: where the strength is (top 5 sectors and strong industries,
with the top-5-sectors model's backtest), the main long and chosen swing lists
(first 10, each pick with its sector, 12-1 momentum, nearness to the high,
quality percentile and P/E, the list's annualised return, Sharpe and worst fall
beside it), the top-down lists, and the likely movers with the evidence of each
setup. `brief_text` prints them as STOCK IDEAS; the workbench draws them before
the news.

### The engineering agent on a small model (HISTORY #78)

`engineering.budget(name)` = 0.8 × the model's `tokens_per_minute` in
`config/llm.yaml` (Groq: 6,400), or None. With a budget, `fixer.fix` builds
`small_context`: `rules_digest` (CLAUDE.md's Truth, Data integrity and Code
sections, at most 3,500 characters); `excerpt` (the module header up to the
first def or class, at most 80 lines, then the innermost function or class
around each line `error_lines` finds in the traceback or `path:line:` findings,
padded by 10 lines, with `# ... lines N-M not shown ...` markers); the test
functions that mention a name shown (`related_tests`); and the error's tail. If
`EDIT_SYSTEM` + context + 1,800 reserved tokens exceed the budget it shrinks the
tests, then the window, then the error, and if nothing fits returns "too big for
this model" without asking. The answer's `edits` and `test_edits` are applied by
`apply_edits` (each `find` exactly once, else `EditFailed`, the tree reset and a
second try told why); `test_append` adds tests. A failed check resets the tree and
retries with the check output and a 60-line window. Then the next model in
`options.models`; one with no limit gets the whole file (`context`, `SYSTEM`), as
before. Requests are paced to the per-minute limit by `assistant/chat.pace`
(ADR-125).
