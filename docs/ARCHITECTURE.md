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

## 4.2 The cost model: itemised, not blended

Trading costs in India are not one number. They are a stack of separate
charges, each with different rules about which side pays. Blending them into
"0.1% round trip" is wrong in both directions.

For a trade of `Q` shares at price `P`, turnover `T = P × Q`:

| charge | rate (equity delivery) | falls on |
|---|---|---|
| Brokerage | 0 (delivery); min(0.03%, ₹20) otherwise | both |
| **STT** (Securities Transaction Tax) | 0.1% of turnover | both, on delivery |
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

---

# Part V — The workbench

## 7.1 Three ways to author a strategy

The web interface (`make workbench`) offers three routes, all producing the
same `Strategy` object:

1. **Describe** — plain English → a language model drafts a spec.
2. **Compose** — pick a feature, a holding count and a rebalance period.
3. **Code** — write `weights(view)` directly.

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
