# How this system works

*A complete walkthrough for someone who has never seen this repository. It
assumes you can read English and follow arithmetic. It does not assume you know
finance, and every term is defined where it first appears.*

---

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

Why so strict? Because every number downstream is derived from these files. If
a raw file can be quietly "fixed", then a result can change without any code
changing, and no investigation will ever find out why. Immutable raw data means
any result is reproducible from first principles.

Local disk is not the storage of record — a Backblaze B2 bucket is (23,230
objects, 4.45 GB). Local copies are pruned once B2 confirms the upload.

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
| `nse_calendar.json` | trading days = dates with a landed cash bhavcopy; a holiday is a weekday between them without one | — |
| `nifty_futures.jsonl` | one line per day: every live Nifty futures contract's open, high, low, close, settlement, open interest and volume, from the same F&O files, fetched over four connections | 20:00 IST that day |
| `nifty_expiries.json` | every Nifty futures expiry (144, 2015-2026), read from F&O bhavcopies fetched from NSE's archive every 15th trading day (each lists the next three monthly contracts). A file lists the *scheduled* date, which can move later, so each date is confirmed by its own day's file (`confirm_expiries`) | — |

The price panel stored only the close before 2026-08-18. `make rebuild-ohlc`
re-reads every panel day's cash bhavcopy from NSE's archive (not B2, whose
2,500 downloads a day would take two days) through the same parser the panel
uses, and `SWAP=1` replaces the panel only if every stored close is reproduced
exactly; the close-only panel is kept beside it.

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

Both series are built in one place, `backtest/history.py`, shared by the two
engines: `back_adjusted` for marking, `HistoryWindows` for signals. Consecutive
signal windows overlap almost entirely (a 253-day window moved 21 days keeps
232 rows), so a window reuses the previous one's adjusted rows whenever the
same actions are knowable and adjusts only the new ones. Each row's divisor is
still the product of the later knowable factors taken newest first, the order
the per-window walk used, so the prices are bit-for-bit the same;
`tests/test_backtest_history.py` keeps that walk as the oracle (ADR-062).

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
                √( 1 − skew·SR + (kurt/4)·SR² )
```

where `n` is the number of return observations and `SR`, `skew`, `kurt` are in
**per-period** units.

Read it as a probability: **DSR = 0.95** means a 95% chance this is not noise.
The mandate requires ≥ 0.95.

Note the denominator. Negative skew makes `−skew·SR` positive, **enlarging** the
denominator and **shrinking** DSR. Fat tails do the same. A strategy with ugly
moments is penalised, correctly.

> **This project's live numbers.** 19 trials are logged. The noise bar is
> currently **Sharpe 1.88**. The best result this project has ever produced is
> **1.27**. Read that again: the best strategy found so far is *below* what
> pure noise would be expected to produce given how much has been searched.

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
system may propose changes in a review; it may not edit them.

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
2. **The verdict is binary.** PROMOTE or KILL. There is no "pass with
   concerns", because a gate that can express reservations will be overruled by
   whoever reads them.
3. **A strategy that fails is dead.** It is not tuned and resubmitted.
   Resubmitting under a new ID is visible in the ledger, which is what the
   ledger is for.

**The holdout** is a slice of data read **exactly once**, by the operator's
action, only after a PROMOTE. There is no un-spend function. A KILL verdict
refuses the read entirely.

**Acceptance:** three deliberately overfit strategies are fed to the gate; all
three must die. They do — killed on deflated Sharpe, PBO and worst-regime.

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

In front of the paper broker the governor runs on a **simulated clock**: the
same window and the same computed waits, but a wait moves the clock forward
instead of sleeping, because nothing on the other side counts messages
(ADR-061). Live keeps real time.

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
`make paper-daily` (the end of `make daily`) brings each active one up to the
latest close by **replaying it from its start** through the Tier B engine with
`OMSExecutor` (ADR-060). Client order ids are deterministic and `OMS.submit`
returns a journalled order without re-sending it, so replayed days re-read
their fills and only new days send. Missed days are caught up in one run.

Timing is the backtest's: decide on day *t*'s close, fill at day *t+1*'s
price, here 5 bps worse (A-048), with Indian costs and 1% of equity kept in
cash for them. Money is marked at raw closes, so a replay cannot re-size a day
already traded; a split on a held name reads as a loss until S-038 is fixed.

**Capital fit.** Before sizing, `fit_to_capital` ranks the strategy's names
(weight, then the strategy's own order) and keeps the largest top-ranked set in
which every name can buy at least one share at today's close, re-weighted to
the same exposure. Off in backtests (`fit_capital=False`).

**Halts.** Each of these trips the deployment's own switch and stops it:
orders still UNKNOWN after asking the broker; a replayed, already-traded day
producing an order the journal never saw (the data changed after the fact);
engine holdings ≠ broker positions. A stale panel is reported, not halted.
Live mode is refused in code until the Kite adapter has placed a supervised
order (T-3336) and live limits exist.

---

# Part V — The workbench

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
| `intraday/` | the minute-bar engine — signals, the bracket executor, and one store per market | `paper_scan`, `bracket`, `us_store` |
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

## Live data and plumbing

The remaining top-level modules. Small, and load-bearing in the way plumbing is:

| module | what it does |
|---|---|
| `quotes` | live prices, Zerodha first and Yahoo second |
| `indices` | index levels — India from the broker, the world from FMP |
| `macro` | macro series from TradingView's keyless public scanner |
| `workspace` | what is shared between tenants and what emphatically is not (ADR-040) |
| `cloud_results` | results mirrored to the bucket the market data lives in (ADR-042) |
| `config`, `env` | typed config from `config/`, and one place that loads `.env` |
| `notify` | telling the operator when an unattended job fails |
| `schemas` | **stub.** Not the order schema — that lives in `oms/` |

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
