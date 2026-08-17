# Building an Autonomous Quant Research & Execution Platform
### A staged build plan for India equities/options → US equities/options → crypto → FX

*Reference document. Version 1.0. Not investment advice — this is an engineering and process plan. All regulatory and tax details are as of August 2026 and must be re-verified against primary sources (SEBI/NSE/BSE circulars, exchange notices, broker docs) before you rely on them.*

---

## 0. Read this first — the honest framing

Three things need saying before the plan, because getting them wrong is the usual cause of death.

**"Error-free" is not achievable; "bounded blast radius" is.** Every production trading system has bugs. World-class systems are not bug-free — they are built so that no single bug can lose more than a pre-agreed amount. The design target is therefore: *invariants that fail loudly, reconciliation that catches drift, and hard limits that cap the damage.* Every chapter below is written toward that goal rather than toward perfection.

**Fully autonomous research is not the same as fully autonomous capital allocation.** AI can do ~80% of the labour: literature mining, hypothesis specification, code generation, backtest orchestration, statistical validation, data-quality triage, log analysis, incident summarisation, reporting. What it must *not* do is decide whether a strategy is real. That decision must be made by a deterministic statistical gate whose thresholds are set once, version-controlled, and changeable only by a deliberate human commit. The moment an LLM can adjust its own pass/fail bar, you have automated the process of fooling yourself.

**Sequencing beats scope.** A platform that trades one strategy in one market with impeccable risk controls is worth more than a half-built platform aimed at five asset classes. The rollout order in Phase 11 exists for a reason: each market forces you to generalise exactly one hard abstraction, and doing them in order means you never have to rewrite the core.

**Order of difficulty, roughly:** India equities (EOD) < US equities < crypto spot/perp < India index options < US options < FX < India single-stock options (physical delivery is brutal) < anything requiring co-location.

---

## Part I — Architecture at a glance

Nine layers. Build them bottom-up; each is independently testable.

```
┌──────────────────────────────────────────────────────────────────────┐
│ 9. AGENT LAYER   ideation · codegen · critic · ops · reporting       │
├──────────────────────────────────────────────────────────────────────┤
│ 8. CONTROL PLANE  IaC · CI/CD · secrets · observability · runbooks   │
├──────────────────────────────────────────────────────────────────────┤
│ 7. PORTFOLIO & RISK  allocator · limits · kill switches · margin     │
├──────────────────────────────────────────────────────────────────────┤
│ 6. EXECUTION  OMS → EMS → SOR → broker adapters → recon             │
├──────────────────────────────────────────────────────────────────────┤
│ 5. VALIDATION  overfitting battery · promotion gates · paper stage   │
├──────────────────────────────────────────────────────────────────────┤
│ 4. SIMULATION  vectorised sweeper + event-driven replay engine       │
├──────────────────────────────────────────────────────────────────────┤
│ 3. RESEARCH  feature/alpha library · experiment tracking · notebooks │
├──────────────────────────────────────────────────────────────────────┤
│ 2. DATA PLATFORM  bitemporal store · quality engine · corp actions   │
├──────────────────────────────────────────────────────────────────────┤
│ 1. SECURITY MASTER  instruments · calendars · symbology · contracts  │
└──────────────────────────────────────────────────────────────────────┘
```

**The single most important architectural rule:** a strategy is written *once*, against one abstract interface, and the same object is used by the backtester, the paper trader, and production. Data source and execution venue are injected. If backtest and live code diverge, your validation is measuring a program you will never run.

```python
class Strategy(Protocol):
    def on_bar(self, ctx: Context) -> list[TargetPosition]: ...
    def on_tick(self, ctx: Context) -> list[Order]: ...
    def on_fill(self, ctx: Context, fill: Fill) -> None: ...
    # ctx exposes ONLY data timestamped <= ctx.now. Enforced at the
    # data-access layer, not by convention. This is non-negotiable.
```

---

## Part II — Phase-by-phase build plan

Week numbers assume one experienced engineer working most-time, with AI assistance. Halve them for a team of three; double them if you are also learning the domain.

---

## Phase 0 — Constraints, compliance, capital (Weeks 1–3)

Do this before writing code. These constraints determine which strategies are even legal or economic for you, and half of them are invisible until they bite.

### 0.1 India — regulatory reality (as of Aug 2026, verify)

SEBI's retail algo framework (circular dated 4 Feb 2025, phased through 2025, **fully mandatory for all brokers from 1 April 2026**) changed the game. What it means practically:

| Requirement | Implication for your build |
|---|---|
| **Static IP whitelisting** — one or two static IPs registered with the broker | Your execution box needs a fixed IP. Rules out consumer broadband and ephemeral cloud IPs. Provision an Elastic IP / static IP in `ap-south-1` (Mumbai) and register it. Plan a documented failover IP too. |
| **Algo-ID tagging** — exchange-assigned identifier on every order placement, modification and cancellation | Your OMS must carry and echo this ID field through the whole order lifecycle. Design your order schema for it from day one; retrofitting is painful. |
| **~10 orders/sec/exchange/client threshold** | Below it, no algo registration for self-developed strategies. Above it, you land in the registered-algo regime with exchange approval per strategy — and any change requires fresh approval. **Design decision: put a hard OPS governor in the EMS, configurable, defaulting well below the threshold.** Treat crossing it as a business decision, not an accident. |
| **Principal–agent model** — broker is principal, algo provider is agent | If you only trade your own capital through your own code, you are the client, not a provider. If you ever let anyone else use your strategies, you are a provider and need a broker partnership. Know which side of that line you're on. |

Also non-negotiable for India:
- **Derivatives contract specs churn constantly.** Index derivative lot sizes are reset to keep notional in a ₹15–20 lakh band, and have been revised repeatedly (Nov 2024, Oct 2025, and again effective the Jan 2026 series — Nifty 50 went 25 → 75 → 65, Bank Nifty 15 → 35 → 30). **Never hardcode a lot size.** Lot size is a time-versioned field in the security master.
- **One weekly index expiry per exchange.** NSE keeps Nifty 50 weekly, now expiring **Tuesday**; BSE keeps Sensex weekly, expiring **Thursday** (both effective Sept 2025). Bank Nifty / FinNifty / Midcap Select weeklies were discontinued in Nov 2024 — they are monthly-only. Any backtest of a Bank Nifty weekly straddle on post-2024 data is testing an instrument that no longer exists.
- **Settlement asymmetry.** Index options are cash-settled on the average underlying over the last 30 minutes (15:00–15:30 IST). **Single-stock options are physically delivered.** A backtest that cash-settles stock options is wrong in a way that will eventually deliver you ₹40 lakh of shares you cannot fund. Also: STT on option *exercise* is charged on notional, not premium — it can exceed the intrinsic value of a marginally-ITM option. Model it or don't trade near-the-money expiry.
- **No calendar-spread margin benefit on expiry day** for the expiring leg (since Feb 2025). Your margin model must know this or you will get squared off by the broker's RMS.
- **Margin regime**: SPAN + Exposure, peak-margin reporting, intraday snapshots. Build a SPAN calculator or consume the exchange PAR files; do not approximate.

### 0.2 US — what matters

- No personal-algo registration, but read your broker's API ToS carefully (rate limits, market-data redistribution, PDT rule if account < $25k).
- **Section 1256** treatment for broad-based index options (60/40 long/short-term) vs equity options; wash-sale rules; constructive sales. This changes after-tax Sharpe materially — model taxes at the strategy level, not as an afterthought.
- Options data is genuinely expensive (OPRA). Budget for it or restrict to liquid underlyings.
- **For Indian residents:** LRS caps outward remittance (currently USD 250k/FY) and imposes TCS above thresholds. This is a hard capacity ceiling on your US book. Offshore CFD/retail-FX platforms are a FEMA grey area — get a professional opinion in writing, in advance.

### 0.3 Crypto & FX from India

- Crypto: **30% flat tax on VDA gains (Sec 115BBH) + 4% cess, 1% TDS on transfers (Sec 194S), and no loss set-off** — retained unchanged in Budget 2026, with new reporting penalties from 1 April 2026. **The 1% TDS is an execution-cost problem, not a tax problem:** a strategy turning over 50× a year pays ~50% of notional in TDS. It kills all high-turnover onshore crypto strategies. Model TDS as a per-trade cost in the backtester or your results are fiction.
- No loss set-off means strategy-level PnL and tax PnL diverge sharply. Two accounting books required.
- FX: exchange-traded INR currency derivatives only, onshore, with underlying-exposure requirements. Global spot FX from India is legally constrained. **Plan FX last, and plan it as an offshore-entity question, not a technical one.**

### 0.4 Your own constraints — write these down

Produce a one-page `mandate.yaml`, version-controlled:
```yaml
capital: {total: X, per_market_cap: {...}}
risk: {max_daily_loss_pct: 1.5, max_strategy_dd_pct: 8, max_portfolio_dd_pct: 15}
targets: {min_deployable_sharpe: 1.2, min_trades_for_significance: 200}
latency_tier: 2               # see Part V
horizons: [daily, intraday_5m]  # explicitly NOT sub-second, for now
excluded: [physical_delivery_options, offshore_cfd]
```
Every promotion gate reads from this file. It is the constitution.

### Phase 0 exit criteria
- [ ] Written compliance memo per market, with citations to primary circulars
- [ ] Broker accounts opened, API keys issued, static IP registered
- [ ] `mandate.yaml` committed
- [ ] Tax treatment documented per instrument type, reviewed by a CA
- [ ] Budget approved for data + infra (see Part VI for realistic numbers)

---

## Phase 1 — Security master & data platform (Weeks 2–10)

**This is where world-class platforms are separated from hobby projects.** Almost every fake backtest edge traces back to a data defect. Spend disproportionate time here.

### 1.1 Security master (build first, always)

A time-versioned instrument registry. Every field is `valid_from`/`valid_to`.

```
instrument
  internal_id (immutable, yours — never an exchange symbol)
  identifiers: {isin, exchange_token, tradingsymbol, figi, cusip, ric, ccxt_symbol}
  asset_class, exchange, currency, segment
  tick_size, lot_size, multiplier, board_lot        ← ALL time-versioned
  option: {underlying_id, strike, expiry, right, exercise_style, settlement_type}
  future: {underlying_id, expiry, settlement_type, delivery_flag}
  listing_date, delisting_date, suspension_periods
  fno_ban_periods (India), lulds/circuit_bands
```

Hard rules:
1. **Internal IDs, never symbols, as the join key.** Symbols change (`Zomato` → `Eternal`); tokens change per broker; CCXT symbols differ per exchange.
2. **A symbology mapping table per broker/vendor**, populated by a daily reconciliation job that alerts on any unmapped instrument. This job will save you more money than any alpha.
3. **Calendars**: trading days, holidays, session times, special sessions (Muhurat), expiry calendars per product, settlement holidays. India, US, and crypto (24/7 with maintenance windows) all differ. Half-days exist and break naive resampling.

### 1.2 Bitemporal storage — the lookahead firewall

Every record carries two timestamps:
- `event_time` — when it happened in the market
- `knowledge_time` — when *you* could first have known it

The research data-access API takes an `as_of` and physically cannot return rows with `knowledge_time > as_of`. This makes whole classes of lookahead bias impossible rather than merely discouraged.

This matters enormously for:
- Fundamentals (reported vs filed vs restated — use point-in-time vendors, never a current snapshot)
- Index constituents (NIFTY 50 reconstitutions; testing today's constituents historically is a massive survivorship bias — often worth several points of fake annual return)
- Analyst estimates, ratings, corporate announcements
- Your own vendor's *revisions* (vendors silently backfill; store what you received, when you received it)

### 1.3 Corporate actions & adjustment engine

Store **unadjusted prices plus an adjustment-factor table**, and adjust on read. Never store only adjusted prices — the vendor's adjustment policy will change and silently rewrite your history.

Handle: splits, bonuses, rights, dividends (special vs ordinary), mergers/demergers (Indian demergers are frequent and messy), name/symbol changes, delistings, and **F&O contract adjustments** (strike and lot revisions on corporate actions).

Futures continuation series: implement all three roll conventions (ratio-adjusted, difference-adjusted, non-adjusted) plus roll rules (calendar-based, volume-crossover, OI-crossover). State which you used in every backtest's metadata. Ratio vs difference adjustment can flip the sign of a trend strategy's backtest.

### 1.4 Storage architecture

```
LANDING (immutable, append-only)      S3 / MinIO, raw vendor payloads, zstd
   ↓ (idempotent, replayable ETL)
CURATED (normalised, bitemporal)      ArcticDB on S3  ← ticks/bars/panels
   ↓
ANALYTICS                             ClickHouse or DuckDB ← ad-hoc SQL, ops metrics
   ↓
FEATURE STORE                         Parquet + registry (or Feast) ← versioned features
   ↓
LIVE STATE                            Redis / shared memory ← positions, latest book
```

**Concrete recommendation:** ArcticDB (Man Group, open source) for time-series — it handles tick and panel data on object storage with versioning built in, and is the closest thing to a free Arctic/kdb+ substitute. ClickHouse for anything you want to SQL over. DuckDB for local research. Reach for kdb+/q only if you get to Tier 3 latency and have budget.

Never keep only the raw landing zone or only the curated store. The landing zone is your ability to rebuild everything after you discover a bug in the ETL — and you will.

### 1.5 Data sources shortlist

**India**
- EOD/bhavcopy, F&O bhavcopy, participant-wise OI, bulk/block deals, SAST/pledge disclosures: NSE/BSE archives (free, scrape carefully and cache)
- Intraday/tick + full option chains: TrueData, GDFL (Global Data Feeds), Dhan/Kite historical APIs, AlgoTest data. For serious options work you need **timestamped full-chain snapshots**, not just the strikes you happen to care about — reconstructing IV surfaces later is impossible otherwise.
- Fundamentals point-in-time: Capitaline, Prowess (CMIE), Refinitiv. Screener-style scrapes are not point-in-time.
- Level-2/TBT: only via broker/exchange co-lo arrangements.

**US**
- Equities: Polygon.io (good value), Databento (excellent — MBO/ITCH, clean DBN format, per-use pricing), Alpaca, Nasdaq TotalView
- Options: CBOE DataShop, Databento OPRA, ORATS or IVolatility for surfaces
- Fundamentals PIT: Sharadar (Nasdaq Data Link), Compustat PIT, Norgate for adjusted price history

**Crypto**
- Live: exchange native WebSockets (Binance, Bybit, OKX, Deribit for options, Hyperliquid)
- Historical L2/trades: Tardis.dev (the standard for order-book history), Kaiko, CoinAPI
- On-chain: Dune, Allium, Flipside; own node for anything latency-sensitive
- CCXT for breadth in the cold path only — never in the hot path

**FX**
- Tick: Dukascopy (free-ish), LMAX, Refinitiv/Bloomberg if institutional; OANDA v20 for retail
- India onshore: exchange currency derivatives via your existing broker

### 1.6 Data quality engine (build this as a first-class product, not a script)

Run as a DAG (Dagster preferred over Airflow for data-asset lineage) on every ingest. Every check produces a versioned result and can block downstream promotion.

**Universal checks**
- Gaps vs calendar; missing instruments vs expected universe count
- OHLC coherence (`low ≤ open,close ≤ high`), non-negative volume, monotone timestamps
- Spike detection with robust statistics (median absolute deviation, not stdev — stdev is broken by the very outliers you're hunting)
- Stale-quote detection (unchanged price with nonzero volume)
- Cross-vendor reconciliation where you have two sources — the single best defect detector that exists
- Timezone/DST correctness: store UTC nanoseconds, keep the exchange timestamp verbatim alongside

**Options-specific no-arbitrage checks** (these catch vendor errors that would otherwise become "alpha")
- Put–call parity within transaction costs
- Monotonicity of calls decreasing / puts increasing in strike
- Butterfly convexity (a negative butterfly is a data error or a real arb — assume the former)
- Calendar monotonicity of total variance
- IV computed *by you* from mid prices with the correct model (Black-76 on futures where applicable), never trusted from the vendor
- Interest-rate and dividend inputs sourced consistently

**Derivatives-specific**
- OI change vs volume consistency
- Contract existence vs security master (catches expired/nonexistent strikes silently present in vendor files)
- Settlement price vs your computed settlement convention

Wire every failure into a ticketed queue with severity. Alert on new failure *classes*, not on every instance, or you will learn to ignore alerts.

### Phase 1 exit criteria
- [ ] Security master with time-versioned lot sizes and full broker symbology mapping, reconciling daily with zero unmapped instruments
- [ ] Bitemporal API where `get(instrument, field, as_of)` provably cannot leak the future (with a test suite that tries to make it leak)
- [ ] Corporate actions engine reproducing a known adjusted series to the paisa
- [ ] Quality DAG green on 10+ years India EOD, 5+ years India options chains
- [ ] Full rebuild from landing zone tested end-to-end and timed

---

## Phase 2 — Research environment (Weeks 8–14)

### 2.1 Engineering baseline

Non-negotiables, because research code becomes production code:
- Monorepo, `uv` for dependency management, Python 3.12+
- `mypy --strict` on all library code; Pydantic for every config and data contract
- `ruff` + pre-commit; pytest with `hypothesis` for property tests
- **Data/code/config versioning that pins all three:** every experiment records `git_sha`, `config_hash`, `dataset_version`. Use DVC or lakeFS for data versioning. If you can't reproduce a six-month-old backtest bit-for-bit, you can't debug a live divergence.
- MLflow (or Weights & Biases) as the experiment registry — every backtest run is an experiment, including failures. **Especially failures:** the graveyard of dead hypotheses is a genuine asset, and it's the thing that stops your agents from re-testing the same dead idea for the twentieth time.

### 2.2 Feature / alpha library

Standardise a signature so features are composable and testable:

```python
@feature(deps=["close", "volume"], min_history="252d", universe="nifty500")
def residual_momentum_12_1(panel: Panel, *, lookback=252, skip=21) -> Series:
    ...  # returns cross-sectional score, index = (date, instrument_id)
```

Every feature gets: unit tests on synthetic input with a known answer, a lookahead test (shifting input forward must not change past output), and NaN-policy documentation.

**Evaluation harness (Alphalens-style, before any backtest):**
- Information Coefficient (Spearman) and IC decay by horizon
- Quantile spread returns, turnover, and IC-to-turnover ratio
- Factor-neutralised residual IC (strip out market, size, value, momentum, low-vol, and sector — India needs a locally-built factor library; do not reuse US factor definitions unexamined)
- Breadth: how many names contribute? An "alpha" driven by three microcaps is not an alpha
- Decay analysis over time — has the edge been arbitraged away since 2019?

Screening at the IC level is 50× cheaper than backtesting, so make it the mandatory first filter.

### 2.3 Options-specific research infrastructure

You need this before any options strategy is testable:
- Pricing library: Black-Scholes, Black-76, binomial/American for single stocks, with your own greeks
- **Arbitrage-free IV surface fitting**: SVI or SSVI per expiry, with SABR as an alternative; enforce no-arb constraints in the fit
- Surface features: ATM vol term structure, 25-delta risk reversal and butterfly, skew slope, vol-of-vol, VRP (implied vs subsequent realised), variance term structure carry
- Greeks aggregation at portfolio level, and a scenario engine (spot × vol × time grid) for stress
- Expiry-day microstructure features: minutes-to-expiry, pinning distance to max-OI strike, gamma imbalance proxies

### Phase 2 exit criteria
- [ ] 30+ tested features across price/volume/fundamental/options-surface families
- [ ] IC harness produces a one-page tear sheet in <2 minutes for any feature
- [ ] Arbitrage-free surface fitter validated against known-good vendor surfaces
- [ ] Experiment registry recording every run with full reproducibility triple

---

## Phase 3 — Simulation engine (Weeks 10–20)

Build **two** backtesters that share one strategy interface.

**Tier A — vectorised sweeper.** Polars/NumPy, daily-to-5-minute bars, no order book. Purpose: scanning thousands of parameter sets and universes in minutes. Deliberately approximate costs, but *conservatively* (over-estimate). Used only for triage — never for a promotion decision.

**Tier B — event-driven replay.** Processes the same event stream the live system consumes, in the same order, through the same strategy object. Purpose: the only backtest that counts. Slower by 100×; that's fine.

### 3.1 Realism checklist for Tier B

Work through every line. Each omission is a systematic bias, almost always in your favour.

**Timing**
- Decision latency: signal computed at `t` cannot produce an order arriving before `t + Δ`. Measure your real Δ and use it.
- Bar-close trap: if you use the 15:29 bar's close, you cannot trade at 15:29's close. Trade at 15:30 open, or model the crossing.
- Data arrival jitter: replay events by *receive* time, not exchange time.

**Fills**
- Never fill at the mid unless you model the queue. Default: market orders cross the spread and pay impact; limit orders fill only when the book trades *through* your price by enough volume.
- Queue-position modelling with L3/MBO replay where you have it. Rule of thumb without it: assume you are at the back of the queue.
- Partial fills, cancel/replace latency, order rejects, and self-impact.
- Market-impact model: square-root law (`impact ≈ σ · √(Q/V)` scaled by a fitted constant) plus a linear temporary component. Calibrate the constant from your own live fills once you have them; use published estimates until then, and haircut them.

**Costs — the India list is long and asymmetric**
- Brokerage, exchange transaction charges, clearing charges
- STT/CTT: different rates for delivery vs intraday vs futures vs options premium vs **option exercise on notional**
- Stamp duty (state-varying), SEBI turnover fee, GST on (brokerage + transaction charges)
- Slippage, impact, borrow cost and *borrow availability* for shorts (in India, intraday-only shorting in cash equities without SLB — a huge constraint most backtests ignore)
- Financing/carry, margin funding rates, negative interest on idle margin
- Crypto: maker/taker tiers, funding payments every 8h, withdrawal fees, **1% TDS if onshore**
- US: SEC fee, TAF, options per-contract fees, exercise/assignment fees, ADR fees, hard-to-borrow rates

**Market mechanics**
- Circuit limits, LULD halts, and freeze quantities (rejected orders above freeze qty is a real India failure mode)
- Opening/closing auctions with their own price formation
- F&O ban periods (India): no new positions in banned scrips — this alone breaks many equity F&O backtests
- Margin: SPAN + exposure, peak margin, intraday snapshot penalties, and the **no calendar-spread benefit on expiry day** rule
- Physical delivery for Indian single-stock derivatives; assignment risk for American options
- Settlement conventions (T+1 India, T+1 US); funds availability constraints

### 3.2 How to test the backtester itself

This is the step everyone skips and it is the difference-maker.

1. **Accounting invariants asserted on every single event.** `cash + Σ(position · mark) == equity`, to the paisa. `Σ fills == position`. Any violation throws. This catches ~70% of engine bugs immediately.
2. **Known-alpha injection.** Generate synthetic price series containing a deliberately planted, precisely-known edge. The engine must recover it within tolerance. If it can't find an edge you *put there*, don't trust it to find real ones.
3. **Zero-alpha test.** Run a random-entry strategy with matched turnover. Expected result: exactly the modelled cost drag, no more, no less. If a coin-flip strategy makes money, your fill model is fantasy.
4. **Property-based tests** (hypothesis): random order sequences must never produce negative positions in long-only mode, never exceed limits, never fill above the ask.
5. **Golden-file regression.** Freeze the full output of a reference strategy on a reference dataset. Any commit that changes it must explain why in the PR. This is how you avoid silently improving your backtests over time.
6. **Determinism.** Same inputs → byte-identical outputs. Seed everything. Non-determinism means you cannot bisect a divergence.
7. **Shadow reconciliation** (once live): replay the exact live event stream through the backtester and diff every order and fill. Target <2bp mean divergence; investigate anything larger. This becomes a permanent nightly job.

### Phase 3 exit criteria
- [ ] Invariant assertions on every event, enabled in production too
- [ ] Known-alpha recovery test passing; zero-alpha test producing exactly modelled costs
- [ ] Cost model reproducing an actual broker contract note line-by-line for 20 real trades
- [ ] Golden-file regression suite in CI
- [ ] Same strategy object runs unchanged in Tier A, Tier B, paper, and live

---

## Phase 4 — The anti-overfitting gauntlet (Weeks 16–22)

**Framework answer, up front:** there is no single tool. What you build is a *deterministic pipeline* combining (a) pre-registration, (b) purged combinatorial cross-validation, (c) multiple-testing-corrected significance, and (d) economic-plausibility gates. Concretely: **López de Prado's CPCV + Deflated Sharpe Ratio + Probability of Backtest Overfitting**, wrapped in your own promotion-gate code, with Harvey–Liu–Zhu haircuts applied to the t-statistic. Details in Part IV; the process is here.

### 4.1 Pre-registration (the cheapest, highest-leverage control)

Before touching test data, commit a signed YAML:

```yaml
hypothesis_id: 2026-08-IN-EQ-047
economic_rationale: >
  Post-earnings drift in Indian mid-caps persists because analyst coverage
  is thin and institutional rebalancing is slow. Expect positive drift for
  5-30 trading days after a large positive surprise.
predicted_sign: positive
universe: nifty_midcap_150
parameters_to_search: {holding_days: [5,10,20,30], surprise_threshold: [1.0,1.5,2.0]}
total_configs: 12                 # ← used for multiple-testing correction
data: {dev: 2010-2018, val: 2019-2022, holdout: 2023-2026 LOCKED}
kill_criteria: {min_dsr: 0.95, max_pbo: 0.30, min_trades: 250}
```

`total_configs` is the crucial field. Multiple-testing corrections are only honest if the trial count is declared *before* searching. Your agents must increment it automatically for every configuration they evaluate, and it must be tamper-evident.

### 4.2 Data partitioning with real teeth

- **Development set** — free exploration
- **Validation set** — limited, budgeted access (log every read; N reads maximum, enforced)
- **Holdout / out-of-time** — the most recent 2–3 years, stored on a separate lakeFS branch with credentials your research process does not have. Unlocked once, by a human, at the final gate. If a strategy fails holdout, **it is dead — you do not return to development and retry**, because that turns holdout into a validation set. Killing it is the whole point.
- **Reserve market** — hold out an entire *market* (e.g. develop on India, confirm the same economics in US/Brazil). Cross-market persistence is the single strongest evidence that an effect is real rather than fitted, because the noise is independent.

### 4.3 Cross-validation done properly

Standard k-fold is invalid for time series with overlapping labels. Use:
- **Purged, embargoed CPCV**: remove training samples whose label windows overlap test windows (purging), plus a gap after each test block (embargo) to kill serial-correlation leakage. Gives many backtest paths instead of one, so you get a *distribution* of Sharpes rather than a point estimate.
- **Anchored and rolling walk-forward** with re-fitting, reporting only the concatenated out-of-sample track.
- Report the **median and 5th percentile** of the CPCV Sharpe distribution, not the mean. You will trade one path, and it may be a bad one.

### 4.4 The stress battery (all automated, all mandatory)

| Test | Pass condition |
|---|---|
| **Parameter plateau** | Performance surface is smooth; neighbours of the chosen params retain ≥70% of Sharpe. A sharp peak is a fit, not an edge. |
| **Cost stress** | Survives 3× modelled costs and 2× slippage with Sharpe > 0.7 |
| **Trade concentration** | Removing the best 5% of trades leaves Sharpe > 0.5 and PnL > 0 |
| **Regime subsampling** | Positive in ≥70% of yearly and volatility-tercile subsamples; no single year contributing >40% of PnL |
| **Timestamp shift** | Delaying all entries by 1 bar degrades performance <30%. A strategy that dies from one bar of delay is capturing microstructure noise or lookahead. |
| **Universe perturbation** | Randomly dropping 20% of the universe, 100 times: 5th-percentile Sharpe still positive |
| **Noise injection** | Adding realistic noise to inputs (or bootstrapping residual returns) leaves the sign intact |
| **Correlation to knowns** | Residual alpha after regressing on market/size/value/momentum/carry/vol-carry is still significant. Otherwise you have re-derived a factor you could buy cheaply. |
| **Capacity** | Projected Sharpe at 5× and 20× intended size; where does impact eat the edge? |
| **Turnover sanity** | Implied holding period is consistent with the economic story you pre-registered |

### 4.5 Statistical significance with multiple-testing control

Compute all of these; log all of them; gate on the pre-registered thresholds:
- **Deflated Sharpe Ratio (DSR)** — adjusts for number of trials, non-normal returns (skew/kurtosis), and sample length. Your headline number.
- **Probability of Backtest Overfitting (PBO)** via combinatorially-symmetric cross-validation — the probability that your selected config is worse than median out-of-sample. Gate at <0.3, ideally <0.2.
- **Minimum Backtest Length** — given N trials, how long a track record is needed for the observed Sharpe to be meaningful? Frequently the answer is "longer than you have", which is itself the finding.
- **White's Reality Check / Hansen's SPA** for "is the best of my N strategies better than nothing?"
- **Romano–Wolf stepdown** or **Benjamini–Hochberg FDR** when promoting a batch of strategies at once.
- **Harvey–Liu–Zhu haircut**: the practical rule of thumb is *demand t > 3.0, not 2.0*, for a factor discovered by search.

### 4.6 The promotion gate as immutable code

```python
# gates.py — thresholds live in mandate.yaml; changing them is a reviewed commit.
def gate_research_to_paper(r: BacktestResult, pre: PreRegistration) -> Decision:
    checks = [
        ("dsr",             r.deflated_sharpe        >= 0.95),
        ("pbo",             r.pbo                    <= 0.30),
        ("min_trades",      r.n_trades               >= pre.min_trades),
        ("cost_3x",         r.sharpe_at_3x_costs     >= 0.70),
        ("plateau",         r.plateau_score          >= 0.70),
        ("top5_removed",    r.sharpe_ex_top5pct      >= 0.50),
        ("delay_1bar",      r.sharpe_delay1 / r.sharpe >= 0.70),
        ("residual_alpha",  r.residual_t_stat        >= 3.00),
        ("regime_hit_rate", r.positive_year_fraction >= 0.70),
        ("declared_trials", r.trials_run             == pre.total_configs),  # anti-tamper
        ("holdout_unseen",  r.holdout_read_count     == 1),
    ]
    failed = [name for name, ok in checks if not ok]
    return Decision(passed=not failed, failures=failed, evidence_hash=r.hash())
```

**No LLM is permitted to call, modify, or interpret this function's thresholds.** Agents produce candidates; this code decides. That separation is the core safety property of the whole autonomous design.

### Phase 4 exit criteria
- [ ] CPCV, DSR, PBO, MinBTL implemented and unit-tested against published example values
- [ ] Full battery runs unattended and emits a signed tear sheet PDF
- [ ] Holdout access technically enforced, with an audit log of reads
- [ ] At least three of your own promising strategies *killed* by the gate — if nothing fails, the gate is too loose

---

## Phase 5 — Forward testing (Weeks 20–28)

Backtest → paper → micro-live → scaled. No skipping steps, no exceptions, no "but this one is obviously good."

### 5.1 Paper trading that is actually informative

Paper trading against a replayed file teaches you nothing. Requirements:
- Live market data feed, real time, same code path as production
- Orders sent to a simulator that models the *current* order book, not to the broker's paper endpoint (broker paper fills are usually unrealistically generous)
- Optionally *also* send to broker paper for cross-check
- **Log both what the simulator filled and what the live book would have allowed.** The gap between them is your fill model's error, and you need to measure it before risking money.

### 5.2 Duration: decide statistically, not by feel

Required observation count to distinguish a true Sharpe `S` from zero at ~95% confidence is roughly `n ≈ (2/S)²` years of daily data, i.e. a strategy with true Sharpe 1.0 needs ~4 years to prove itself and no amount of paper trading will shortcut that. So:
- Paper period is **not** for proving the alpha (the backtest did that). It is for proving the *implementation*: no crashes, no reject storms, fills within tolerance, correct margin, correct positions after every corporate action.
- Practical minimum: 1 month or 100 trades, whichever comes later, plus at least one expiry cycle for anything derivatives-related, plus one month-end, one holiday, and ideally one high-volatility day.

### 5.3 The reality-gap attribution report (build this; it is your most valuable dashboard)

Automatically decompose live-vs-backtest PnL difference each day into:
```
backtest_pnl
  − signal_divergence      (different signal computed live? data timing?)
  − missed_trades          (orders not sent: rate limits, halts, insufficient margin)
  − fill_price_slippage    (arrival price vs actual fill)
  − partial_fill_effect
  − timing_delay_cost      (decision→ack latency)
  − unmodelled_costs       (fees, funding, TDS, borrow)
  − residual               ← if this is large, you have a bug
= live_pnl
```
Every dollar must land in a named bucket. A large `residual` is the alarm that finds bugs you'd otherwise attribute to bad luck for six months.

### 5.4 The capital ladder

| Stage | Allocation | Promote when |
|---|---|---|
| Paper | 0 | 1 month + 100 trades, residual attribution <10% of PnL |
| Micro | 1–2% of book | 1 month, live/backtest Sharpe ratio >0.6, zero ops incidents |
| Half | 25–50% of target | 3 months, rolling 60d Sharpe within CPCV 25th percentile |
| Full | 100% of target | 6 months, no drawdown breach |
| Demote/kill | — | Automatic, per pre-registered criteria below |

**Pre-commit the kill rules** (in `mandate.yaml`, before deployment):
- Live drawdown > 1.5× worst backtest drawdown → auto-flatten and halt
- Rolling 60-day Sharpe below the CPCV 5th percentile → halve size
- Live/backtest return ratio < 0.4 over 3 months → demote to paper
- Any unexplained attribution residual > 20% of PnL → halt pending investigation

Automating the *stop* is more valuable than automating the *start*. Humans are reliably bad at cutting their own strategies.

---

## Phase 6 — Execution: OMS / EMS / broker adapters (Weeks 18–30)

### 6.1 Component layout

```
strategy containers (N)
      │  target positions / orders  (in-proc or via message bus)
      ▼
PORTFOLIO MANAGER   nets across strategies, applies allocator weights
      ▼
PRE-TRADE RISK      hard limits — the last line of defence, synchronous
      ▼
OMS                 order lifecycle state machine, idempotency, persistence
      ▼
EMS / SOR           slicing algos, venue choice, OPS governor
      ▼
BROKER ADAPTERS     one per venue, normalising to your canonical schema
      ▼
RECONCILER          broker is truth; continuous position/cash/order diff
```

### 6.2 Correctness patterns that matter most

**Idempotency.** Every order gets a deterministic client order ID: `hash(strategy_id, signal_time, instrument_id, sequence)`. Retrying after a timeout must never double-send. This single pattern prevents the most expensive class of bug in retail algo trading: the network blip that becomes a doubled position.

**The broker is the source of truth, always.** Your position record is a cache. On startup, and every 30–60 seconds, fetch positions/orders/funds and diff. On mismatch: halt new orders, alert, do not "fix" automatically (auto-correction of a phantom mismatch can double the error).

**Explicit order state machine**, persisted before every transition:
```
NEW → PENDING_NEW → ACKED → {PARTIALLY_FILLED} → FILLED
                          ↘ PENDING_CANCEL → CANCELLED
                          ↘ REJECTED
                          ↘ UNKNOWN  ← timeout; must be resolved by query, never assumed
```
`UNKNOWN` is the state that kills people. Handle it explicitly: query, escalate, block new orders in that instrument until resolved.

**Event sourcing.** Append-only log of every input event and every decision. You can then replay any day exactly, answer "why did we place that order at 14:32:07" definitively, and satisfy audit requirements. Non-negotiable if you ever want to debug a live incident properly.

**Every order tagged** with `strategy_id`, `git_sha`, `config_hash`, `signal_id`, and the exchange Algo-ID (India). Without this, PnL attribution across N strategies is guesswork.

### 6.3 Broker & venue adapters

Write one **canonical domain model** (Instrument, Order, Fill, Position, Account, Balance). Adapters translate. Never let a broker's JSON shape leak upward — that is how you end up unable to add a second broker.

- **India retail/prosumer APIs:** Zerodha Kite Connect, Dhan, Fyers, Angel One SmartAPI, Upstox, Alice Blue, Kotak Neo. Confirm each is compliant with the April 2026 framework and supports Algo-ID passthrough. **Verify static-IP registration and OPS limits per broker — they differ.**
- **India institutional:** Symphony XTS, Greeksoft, uTrade, ODIN; FIX connectivity and co-location via the broker if you go Tier 3.
- **US:** IBKR (TWS API, Client Portal, or FIX for larger accounts) is the workhorse for multi-asset; Alpaca for clean equities REST; Tradier/TastyTrade for options; Lime/Clear Street if you scale up.
- **Crypto:** native WebSocket + REST per exchange for anything you care about; CCXT for breadth and for non-latency-sensitive venues. Deribit for crypto options. Use exchange sub-accounts per strategy — the cleanest PnL attribution you will ever get.
- **FX:** OANDA v20, IBKR, LMAX; India onshore currency derivatives via your equity broker.

**Adapter test requirement:** a conformance test suite that every adapter must pass — place, partially fill, cancel, reject, timeout, reconnect mid-order, duplicate ack, out-of-order fill. Run it against each broker's sandbox in CI. Adapters are where 80% of your production incidents will originate.

### 6.4 Execution algorithms

Start simple, add sophistication only when measurement shows it pays:
- Level 0: market orders with a price collar (reject if >X bps from last)
- Level 1: limit-at-touch with timeout-to-market escalation
- Level 2: TWAP/VWAP, POV (participation rate), iceberg
- Level 3: implementation-shortfall optimiser (Almgren–Chriss), adaptive pegging
- Options: prefer exchange-supported multi-leg/spread orders where liquidity exists; otherwise leg in with a **leg-risk guard** (if leg 2 doesn't fill within N seconds, unwind leg 1 immediately — never carry a naked leg by accident)

Measure every execution against arrival price and log implementation shortfall per order. This dataset calibrates your backtest's impact model — the feedback loop that makes your simulator progressively more honest.

### 6.5 Kill switches (design these before the first live order)

Four independent layers, each able to act without the others:

1. **Pre-trade, synchronous** — max order notional, max order quantity vs freeze qty, price collar vs LTP, max OPS, max open orders, instrument allow-list, F&O ban check, margin sufficiency, duplicate-signal detection.
2. **In-flight monitors, separate process** — daily loss limit, per-strategy loss limit, position-vs-target drift, greeks limits (net delta/gamma/vega), stale-data detector (no tick in N seconds → flatten or freeze), clock-skew detector, margin utilisation ceiling.
3. **Dead-man's switch** — the strategy process emits a heartbeat; if it stops, a watchdog cancels all open orders. Enable exchange/broker **cancel-on-disconnect** where offered. This protects you from the crash you didn't anticipate.
4. **Manual panic button** — a single command (and a mobile-accessible endpoint) that cancels everything and flattens, implemented in a **separate codebase and process** from the strategies, using its own credentials. It must work when the main system is wedged. Test it monthly, in production, on purpose.

### Phase 6 exit criteria
- [ ] Adapter conformance suite passing for two brokers minimum
- [ ] Chaos tests: kill the process mid-order, pull the network, force a duplicate ack — the system recovers to a correct state every time
- [ ] Reconciler detects an injected artificial mismatch within one cycle
- [ ] Panic button tested live, with a stopwatch (target: flat in <10s)
- [ ] Zero-quantity live smoke test placing and cancelling one real order end-to-end

---

## Phase 7 — Portfolio, risk and capital allocation (Weeks 26–34)

Individual strategy Sharpe matters less than the portfolio's. Two Sharpe-0.8 strategies at −0.2 correlation beat one Sharpe-1.2 strategy.

- **Allocator:** start with inverse-vol or Hierarchical Risk Parity (robust, no matrix inversion). Graduate to mean-variance with Ledoit–Wolf shrinkage only if you can demonstrate out-of-sample improvement. Cap any single strategy's risk contribution (e.g. ≤25%).
- **Sizing:** fractional Kelly at 0.25–0.5× of full Kelly, with a vol target overlay (scale exposure inversely to realised vol so risk stays constant across regimes). Full Kelly is mathematically optimal and practically ruinous under parameter uncertainty.
- **Drawdown-responsive de-risking:** a pre-specified rule that reduces size as drawdown deepens, and a pre-specified re-entry rule. Both written before you need them.
- **Correlation monitoring:** rolling correlation of *live* strategy returns, alerting when strategies converge (crowding into the same trade is how a diversified book becomes one leveraged bet).
- **Margin efficiency:** portfolio SPAN optimisation for options books; US portfolio margin; cross-margin on crypto. A strategy that's uneconomic at strategy-margin can be strongly economic at portfolio-margin — but only if your margin model is accurate.
- **Currency & cross-market:** USD/INR exposure from the US book, LRS remittance limits as a hard capacity constraint, and repatriation friction in your capital planning.
- **Tax-aware overlay:** India F&O as business income, STCG/LTCG on equities, VDA at 30% with no loss set-off, US 1256 60/40 and wash sales. Build a tax-lot engine. After-tax Sharpe is the only Sharpe that pays your bills, and for high-turnover crypto in India it can be *negative* while pre-tax is positive.

---

## Phase 8 — Latency engineering

### 8.1 First decide your tier — most people over-engineer this

| Tier | Horizon | Tick-to-trade budget | Stack | Cost |
|---|---|---|---|---|
| **1** | Daily / EOD | seconds–minutes | Python anywhere | ~free |
| **2** | Intraday, minutes to seconds | 5–50 ms | Python + async, cloud VM in-region | $100s/mo |
| **3** | Sub-second, quote-reactive | 100 µs – 5 ms | Rust/C++, bare metal, kernel bypass | $10k+/mo |
| **4** | Latency arbitrage | < 10 µs | FPGA, co-location, microwave | $1M+/yr |

**Be honest about Tier 4.** Competing on pure speed against firms with FPGAs at NSE co-lo is not a fight you win by writing better Python. If your edge is statistical rather than a race, Tier 2 is genuinely sufficient and 99% of your returns will come from data quality and risk control, not microseconds. Build for Tier 2 with a clean path to Tier 3.

### 8.2 Measure before optimising

- Instrument the full path: `exchange_ts → feed_receive → parse → signal → order_create → risk_check → socket_write → broker_ack → exchange_ack`
- Record **p50, p99, p99.9, and max** — never the mean. Tail latency is what costs you money; a 50 ms p99.9 during the open is worth more attention than shaving the median.
- Use `time.perf_counter_ns()` in Python, `rdtsc`/`std::chrono::steady_clock` in native code
- Hardware timestamping (Solarflare/Exablaze NIC, or Beeks/Corvil taps) if Tier 3+
- Distributed tracing (OpenTelemetry) for the cold path only — its overhead is unacceptable in the hot path
- **Ship a latency histogram to Grafana continuously.** Latency regressions from a dependency upgrade are otherwise invisible.

### 8.3 Tier 2 wins, in order of payoff-per-effort

1. **Co-locate your compute with the broker.** AWS `ap-south-1` (Mumbai) for Indian brokers; `us-east-1`/NY-metro for US; Binance is on AWS Tokyo (`ap-northeast-1`) — being in the wrong region costs 150–250 ms round trip and dwarfs every code optimisation you could make. This is usually a 10× improvement for an afternoon's work.
2. **Persistent connections.** Keep WebSockets and HTTP/2 sessions warm; pre-authenticate; refresh tokens before expiry, never on demand. TCP handshake + TLS + auth on the critical path is 100 ms+ thrown away.
3. **`TCP_NODELAY`** on every socket (disable Nagle). One line, often 40 ms.
4. **Pre-compute everything possible before the event arrives.** Precompute strike selection, greeks grids, order templates. At decision time you should be filling in a price, not building an object graph.
5. **Never parse JSON in the hot path** if a binary feed exists. Where JSON is unavoidable, use `orjson`/`msgspec`, and parse only the fields you need.
6. **Avoid rate-limit induced latency.** Track your own quota consumption; queue and prioritise. A 429 response is a multi-second latency spike.
7. **Separate the fast path from the slow path.** Logging, metrics, and database writes go to a queue consumed by another thread/process. Never block a decision on a disk or network write.

### 8.4 Tier 3 techniques

**Software**
- Rust or C++ for the execution core. Rust is the better default in 2026: comparable performance, dramatically fewer memory-safety incidents, good tooling. Keep the hot path synchronous and spinning; async runtimes add scheduling jitter.
- Zero allocation in the hot path: arena/pool allocators, preallocated ring buffers, no `Vec::push`, no GC language
- Lock-free SPSC/MPSC ring buffers (LMAX Disruptor pattern); Aeron or Chronicle Queue for IPC; shared memory over loopback TCP
- Cache-line alignment; avoid false sharing; keep hot structs within a cache line; struct-of-arrays over array-of-structs
- Busy-spin polling instead of `epoll` when a core can be dedicated
- Binary wire formats: SBE, Cap'n Proto, FlatBuffers, or the exchange's native binary protocol
- Branch-predictable code; `likely`/`unlikely` hints; SIMD for surface fitting and greeks

**System tuning**
- Pin threads to isolated cores (`isolcpus`, `nohz_full`), disable hyperthreading on hot cores
- CPU governor to `performance`, disable C-states and turbo variability, disable SMT/CPU frequency scaling
- Huge pages; NUMA-local memory and NIC placement
- IRQ affinity away from hot cores; disable `irqbalance`
- PTP time sync (not NTP) with hardware timestamping

**Network**
- Kernel bypass: Solarflare Onload / `ef_vi`, DPDK, or RDMA
- Multicast market data handling with sequence-gap recovery
- Co-location (NSE co-lo, CME Aurora, Equinix NY4/LD4/TY3), cross-connects
- FPGA tick-to-trade only when you have proven that the last microsecond is where your PnL lives

**Reality check:** each of these buys less than the previous one, and all of them together buy less than a correct fill model. Do not enter Tier 3 until measurement proves latency — not slippage, not sizing, not costs — is the binding constraint on a specific strategy's PnL.

### 8.5 Language architecture that doesn't force a rewrite

```
Python:  research, feature engineering, strategy definition, orchestration
   │     (strategies expressed declaratively / as a restricted DSL)
   ▼
Rust:    event loop, feed handlers, OMS state machine, risk checks, adapters
   │     (exposed to Python via PyO3 for backtesting the identical code)
   ▼
FPGA:    only if Tier 4
```
Bind with PyO3/`maturin` so the *same* Rust execution core runs in the backtester and in production. This is how you avoid the classic disaster of a fast C++ production system that behaves differently from the Python backtest that approved the strategy.

---

## Phase 9 — Control plane: SRE, observability, disaster recovery

### 9.1 Infrastructure

- **IaC for everything:** Terraform for cloud resources, Ansible for host config. Zero manual server changes — a hand-tuned box you can't rebuild is a liability.
- **Environments:** `dev` → `sim` → `paper` → `prod`, identical container images, differing only in injected config and credentials.
- **Where to run what:** Kubernetes is fine for research, data pipelines, dashboards, and Tier 1–2 strategies. It is a poor fit for Tier 3 latency (scheduler jitter, network abstraction overhead) — use dedicated bare metal or pinned VMs there.
- **Secrets:** Vault or AWS Secrets Manager. Never in the repo, never in env files on disk. **Separate API keys per strategy with least privilege** — and where the broker supports it, keys that cannot withdraw funds. For crypto, always: trade-only keys, IP-whitelisted, withdrawal disabled.
- **Sub-accounts per strategy** wherever the venue allows. Free, perfect PnL attribution and blast-radius isolation.

### 9.2 CI/CD with trading-specific gates

```
commit
 ├─ ruff + mypy --strict
 ├─ pytest unit + hypothesis property tests
 ├─ lookahead lint (static analysis: flags any .shift(-n), future indexing, as_of bypass)
 ├─ golden-file backtest regression (any PnL change must be explained in the PR)
 ├─ adapter conformance suite vs broker sandboxes
 ├─ container build, signed and versioned
 └─ deploy: canary at 10% size → 4h observation → full
```

Rules: no deploys during market hours except rollbacks. Blue-green for strategy containers. Immutable artefacts — you deploy a version, never a branch. Every live order carries the deploying `git_sha`.

### 9.3 Observability

Prometheus + Grafana + Loki + Alertmanager, with alerts to Telegram/PagerDuty. Minimum metric set:

**Data:** feed lag per source, tick rate vs expected, gap count, quality-check failures, staleness
**Execution:** order rate, reject rate by reason, fill ratio, implementation shortfall vs arrival, cancel latency, OPS headroom, rate-limit headroom
**Risk:** live PnL vs expected band, drawdown, margin utilisation, net greeks, position vs target drift, reconciliation break count
**System:** heartbeats, p99 latency per stage, memory, GC pauses, clock skew, disk, connection state

**Alert design:** page for anything that means money is at risk *right now* (recon break, heartbeat loss, limit breach, feed dead during market hours). Everything else goes to a daily digest. Alert fatigue is a genuine safety failure — an engineer who ignores alerts is worse than no alerts.

### 9.4 Runbooks + game days

Write and *rehearse* runbooks for: broker API outage, market-data feed death, exchange halt mid-position, network loss with open orders, doubled fill, position mismatch, margin call, wrong-instrument order, corporate action mishandled, expiry-day assignment surprise, strategy losing money faster than its limit.

Run a **monthly game day** in production: kill a strategy process mid-order, block the broker's IP with a firewall rule, inject a stale feed, fire the panic button. Systems that have never failed under controlled conditions will fail under uncontrolled ones.

**DR:** secondary broker account pre-funded and pre-tested; secondary region/VM able to take over; mobile access to the flatten endpoint; documented "how to trade manually if everything is down" procedure. Test the failover quarterly, not theoretically.

---

## Phase 10 — The AI / agent layer

This is the part you asked about most directly, so here is the design in full — including where it must be deliberately limited.

### 10.1 What to automate vs what to keep deterministic

| Agent | Job | Autonomy |
|---|---|---|
| **Scout** | Crawl SSRN/arXiv/journals/quant blogs/exchange circulars; dedupe against your graveyard; emit structured hypothesis cards | Fully autonomous |
| **Specifier** | Turn a hypothesis into a pre-registration YAML with universe, params, predicted sign, trial count | Autonomous, human sign-off on `total_configs` |
| **Coder** | Implement the strategy against the `Strategy` protocol + write its unit tests | Autonomous; must pass CI including lookahead lint |
| **Critic (red team)** | Adversarially attack its own sibling's code: hunt lookahead, survivorship, omitted costs, unrealistic fills, regime dependence. Separate model/prompt, incentivised to find flaws | Autonomous; its findings are blocking |
| **Orchestrator** | Run Tier A sweep → Tier B backtest → full stress battery; assemble evidence pack | Autonomous; **cannot alter thresholds** |
| **Data medic** | Triage quality-check failures, root-cause, propose fixes, open PRs | Autonomous for diagnosis; human merge |
| **Ops** | Log triage, incident timelines, postmortem drafts, runbook step suggestions | Read-only in prod; **no write access to trading systems** |
| **Analyst** | Daily attribution report, weekly strategy review, monthly portfolio review | Fully autonomous |
| **PROMOTION DECISION** | — | **Deterministic code only. No LLM.** |
| **CAPITAL ALLOCATION** | — | **Deterministic code + human sign-off above a size threshold** |

### 10.2 Non-negotiable guardrails

1. **No agent ever holds production trading credentials.** Agents operate on research and paper environments. Promotion to prod is a signed human action or a deterministic gate — never an LLM tool call.
2. **The statistical gate is code, not judgment.** An LLM's opinion that "this looks robust" carries zero weight in the pipeline. It can *write* the report; it cannot *be* the report's conclusion.
3. **Agent-generated code goes through identical CI** — no fast lane, no "it's just a research script."
4. **Trial counting is automatic and tamper-evident.** Every configuration an agent evaluates increments a counter in an append-only log. The gate compares the log to the pre-registration. This is what prevents the agent from silently searching 10,000 configs, reporting the best one, and claiming it tested twelve. Without this, autonomous research is an overfitting machine.
5. **Sandboxed execution** with resource and network limits; no arbitrary network egress from code-execution sandboxes.
6. **Cost and rate budgets** per agent per day, with hard caps.
7. **Full audit trail:** every agent action, prompt, tool call, and output logged and replayable.
8. **Evals for the agents themselves:** a benchmark set of known-good and known-bad (deliberately overfit, deliberately lookahead-contaminated) strategies. The Critic must catch the bad ones. Measure its catch rate; regressions in agent quality are otherwise invisible.

### 10.3 Implementation

- Orchestration: LangGraph or a plain state machine — deterministic, resumable, inspectable. Avoid frameworks that hide control flow; you need to audit exactly what ran.
- Expose your platform to agents as **MCP servers**: `data-access`, `backtest-runner`, `feature-registry`, `graveyard-search`, `docs`. Typed, permissioned, rate-limited tools. Agents should never touch raw filesystems or databases.
- **The graveyard as a first-class knowledge base:** vector-index every failed hypothesis with *why* it failed. Query it before every new hypothesis. This is what stops the Scout from proposing "momentum on Nifty" every week and is the compounding asset of the whole system.
- Human-in-the-loop checkpoints: pre-registration approval, holdout unlock, capital increase, any change to `mandate.yaml` or `gates.py`.

### 10.4 What AI genuinely does well here

Realistic expectations, in descending order of value:
1. **Volume of validated hypotheses.** Going from 5 to 100 properly pre-registered, properly tested ideas per month. Most fail — that's the point. Throughput against a strict gate is the actual edge.
2. **Adversarial code review.** LLMs are unusually good at spotting lookahead bias and missing cost terms when explicitly tasked to hunt for them.
3. **Infrastructure and adapter code.** Broker adapters, conformance tests, dashboards, ETL — high-volume, well-specified, tedious work.
4. **Ops triage and postmortems.** Correlating logs across services and writing coherent incident timelines.
5. **Literature mining.** Reading everything you don't have time for and mapping it to your framework.

And where it disappoints: **generating genuinely novel alpha from thin air.** Treat LLM-proposed signals as cheap lottery tickets to be run through the gate, not as insight. The compounding advantage is the *pipeline throughput against a strict gate*, not the model's market intuition.

---

## Phase 11 — Market rollout sequencing

Each step forces exactly one new abstraction. Do them in this order and you never rewrite the core.

| Order | Market | New abstraction forced | Why here |
|---|---|---|---|
| 1 | **India equities, EOD** | Security master, corp actions, costs, calendars | Home market, cheapest data, you know the microstructure, no latency pressure |
| 2 | **India index options** | Contract specs, margin/SPAN, greeks, expiry mechanics, IV surfaces | World's deepest index options liquidity; you already have the underlying data |
| 3 | **US equities** | Multi-currency, multi-timezone, second broker, PIT fundamentals, real shorting | Cleaner data and mechanics; validates that your framework generalises |
| 4 | **US options** | American exercise, assignment, portfolio margin, 1256 tax, OPRA scale | Hardest data problem; do it after your options stack is proven |
| 5 | **Crypto perps/spot** | 24/7 operations, funding, sub-accounts, exchange risk, no circuit breakers | Forces real operational maturity — no market close to hide behind, no regulator, real counterparty risk. **Onshore India: model 1% TDS first; it kills most high-turnover ideas before you write any code.** |
| 6 | **Crypto options** | Deribit conventions, inverse contracts, 24/7 greeks management | Natural extension once 2, 4, 5 are done |
| 7 | **FX** | Rolling settlement, swap points, quote conventions, regulatory structure | Legally the most constrained from India — resolve entity/structure questions before building |
| 8 | **Commodities / intl equities** | Delivery, warehousing, market-specific calendars | Optional; only if you find an edge |

**Generalisation checkpoints.** After each market, refactor these until they are truly venue-agnostic: calendar/session model, fee/tax model, margin model, symbology, settlement, currency, order-type mapping, market-state model (halted/auction/closed/pre-open). If adding market N+1 requires touching the strategy layer, your abstraction is wrong — stop and fix it before proceeding.

---

## Part III — Strategy research catalogue

Mine the known families first — they are documented, testable, and give you a baseline. Novel work is much more productive once you know what the standard effects look like *in your own data with your own costs*. A large fraction of published effects will not survive Indian transaction costs, and knowing which is itself valuable.

### India equities
Cross-sectional momentum (12−1, and residual momentum after factor-stripping) · short-term reversal (1–5 day) · low-volatility and betting-against-beta · quality (gross profitability, accruals, earnings quality) · value composites (EV/EBITDA, P/B, FCF yield) · PEAD / earnings-surprise drift · analyst revision momentum · index inclusion/exclusion around NIFTY & Sensex reconstitutions · **promoter pledge changes and SAST disclosures** · bulk/block deal follow-through · buyback and rights announcements · seasonality (month-of-year, pre-holiday, budget-week) · cash–futures basis and roll-yield (structurally rich in India) · SLB lending-rate signals as short-interest proxy · pairs/cointegration stat-arb within sectors · **F&O ban entry/exit effects** · delivery-percentage signals

### India index options
Short premium with delta hedging around the **Tuesday (Nifty) and Thursday (Sensex)** expiry cycles · IV term-structure and skew mean reversion · variance risk premium harvesting · event vol (RBI policy, Union Budget, election results, monthly inflation) · calendar and diagonal spreads · ratio spreads · positioning signals from participant-wise OI (FII/DII/pro/client) · expiry pinning toward max-OI strikes · gamma-imbalance proxies · overnight vs intraday vol decomposition · dispersion (index vol vs constituent vol) where liquidity permits

*Caveats to model explicitly:* the Nov 2024 regime change (single weekly per exchange, tripled lot sizes, no expiry-day calendar margin benefit) means **pre-2025 backtests of short-premium strategies are not representative**. Weight recent data heavily and re-derive rather than assuming continuity. Bank Nifty weekly strategies are untradeable — the instrument was discontinued.

### US equities
The full academic factor zoo, but with the discipline of asking "is this already in a cheap ETF?" · residual momentum · post-earnings drift · short-interest and squeeze dynamics · index-rebalance flow · M&A/merger arb · ETF creation/redemption and NAV arb · seasonality and turn-of-month · intraday reversal patterns · 13F/insider-filing signals · options-implied signals for equity direction (skew, put/call, unusual volume)

### US options
Variance risk premium (index vs single-name) · dispersion / correlation trading · 0DTE structures with explicit tail modelling · earnings-cycle straddle buying/selling · term-structure roll-down carry · skew mean reversion · dealer gamma positioning (GEX-style) · vol-of-vol and VIX-complex term structure · put-spread collars for tail-hedged carry · box spreads as financing

### Crypto
Perpetual funding-rate carry (the flagship crypto trade — cash-and-carry basis) · cross-exchange spot/perp basis · triangular and cross-venue arb (latency-bound) · CEX–DEX spread capture · trend/momentum on majors (one of the few markets where classic trend still works well) · liquidation-cascade prediction from OI and funding · stablecoin depeg mean reversion · Deribit vol carry and term structure · on-chain flow signals (exchange netflows, stablecoin issuance) · funding-rate arbitrage across venues

*Caveats:* exchange counterparty risk is a first-order term, not a footnote — size per venue accordingly, sweep profits out, never keep the whole book on one exchange. Onshore India, model 1% TDS before anything else.

### FX
Carry (rate differentials, risk-adjusted) · trend-following (still one of the most robust effects in FX) · value/PPP mean reversion at long horizons · momentum · dollar-factor and risk-on/risk-off beta · fixing-window effects (4pm London) · order-flow signals if you have them · vol carry on FX options

### Generating *new* strategies systematically
1. **Economic-mechanism first, always.** Write the mechanism before the code: *who* is on the other side, *why* they trade against you, and *why the compensation persists*. "The model found it" is not a mechanism, and effects without mechanisms don't survive.
2. **Systematic feature crossing** across your feature library, with combinatorics counted and declared for the multiple-testing correction.
3. **Genetic programming / symbolic regression** over your feature primitives (gplearn, AlphaGen; Alpha101/Alpha191 as seed populations). Extremely prone to overfitting — mandatory CPCV + DSR, and demand a post-hoc economic interpretation before promotion.
4. **ML on well-posed targets.** LightGBM on cross-sectional ranks beats deep nets in most financial contexts and is far more interpretable. Use triple-barrier labelling and meta-labelling (AFML) to separate "which direction" from "how confident, size accordingly." Reserve RL for *execution* optimisation, where the reward signal is dense and the environment is nearly stationary — not for alpha, where it isn't.
5. **Structural-change mining.** Regulatory and market-structure changes create temporary, mechanically-explicable inefficiencies. The India expiry-day migration and lot-size revisions are exactly this kind of event. Have the Scout agent monitor exchange circulars as a *data source*, not just news.
6. **Cross-market transplant.** Test effects documented in the US on India and vice versa. Independent noise makes cross-market persistence powerful evidence.

---

## Part IV — Overfitting test battery: the concrete framework

**Direct answer to "which framework to test overfitting":** there is no off-the-shelf product that does this properly. Assemble this:

| Concern | Method | Library / source |
|---|---|---|
| Leakage from overlapping labels | Purging + embargo | Implement from *Advances in Financial ML* (López de Prado), ch. 7 |
| One-path illusion | Combinatorial Purged CV (CPCV) | `mlfinlab`-style implementation, or roll your own (~200 lines) |
| Selection bias from N trials | **Deflated Sharpe Ratio** | Bailey & López de Prado (2014) |
| Probability you picked a fluke | **PBO via CSCV** | Bailey, Borwein, López de Prado, Zhu (2015) |
| Is the backtest long enough at all | Minimum Backtest Length | Same authors |
| Best-of-N significance | White's Reality Check; Hansen's SPA | `arch` package (Kevin Sheppard) has SPA/StepM |
| Family-wise error across a batch | Romano–Wolf stepdown; Benjamini–Hochberg | `arch`, `statsmodels` |
| Discovered-factor t-stat inflation | Harvey–Liu–Zhu haircut → **require t > 3** | Harvey, Liu & Zhu (2016), *…and the Cross-Section of Expected Returns* |
| Path dependence / small-sample | Stationary and block bootstrap | `arch.bootstrap` (`StationaryBootstrap`, `CircularBlockBootstrap`) |
| Parameter fragility | Plateau/sensitivity surface scan | Custom; visualise it, don't just score it |
| Factor redundancy | Residualisation vs a locally-built factor set | Custom (India factors ≠ US factors) |
| Backtest realism | Shadow reconciliation vs live | Custom — the ultimate test, and the only one with no assumptions |
| Vectorised sweeping | `vectorbt` / `vectorbtpro`, or custom Polars | For Tier A only |

**Recommended reading, in order:** López de Prado, *Advances in Financial Machine Learning* (the CV and overfitting chapters are the practical core); Bailey & López de Prado on DSR and PBO; Harvey, Liu & Zhu on t-stat haircuts; Almgren & Chriss on optimal execution; Grinold & Kahn on the fundamental law; Bouchaud et al., *Trades, Quotes and Prices* for microstructure and impact.

**The meta-principle:** every one of these tests can be gamed if you run it, fail, tweak, and re-run. The battery's validity comes entirely from pre-registration and trial counting. **Build the counting infrastructure before the tests** — otherwise you have built an elaborate ritual that produces false confidence, which is strictly worse than no tests at all.

---

## Part V — Reference stack summary

| Layer | Recommended | Alternatives |
|---|---|---|
| Language (research) | Python 3.12 + Polars | pandas, R |
| Language (execution) | Rust (PyO3 bindings) | C++, Go, Python for Tier 1–2 |
| Time-series store | **ArcticDB** on S3/MinIO | kdb+, QuestDB, TimescaleDB |
| Analytics | ClickHouse; DuckDB locally | BigQuery, Snowflake |
| Orchestration | **Dagster** | Airflow, Prefect |
| Data versioning | lakeFS or DVC | Delta Lake, Iceberg |
| Experiment tracking | MLflow | Weights & Biases |
| Data quality | Great Expectations + custom no-arb checks | Soda, Pandera |
| Backtest (Tier A) | `vectorbt` or custom Polars | `bt`, `zipline-reloaded` |
| Backtest (Tier B) | **Custom** — share code with prod | Nautilus Trader (good open-source base), QuantConnect LEAN |
| Stats | `arch`, `statsmodels`, `scipy`, custom DSR/PBO | `mlfinlab` |
| ML | LightGBM, scikit-learn | PyTorch for sequence models |
| Options | QuantLib + custom SVI/SABR fitter | `py_vollib` |
| Live state | Redis; shared memory Tier 3 | Aeron, Chronicle |
| Message bus | NATS or Redis Streams; Aeron Tier 3 | Kafka (too much latency for hot path) |
| Metrics | Prometheus + Grafana + Loki | Datadog |
| IaC | Terraform + Ansible | Pulumi |
| Secrets | Vault / AWS Secrets Manager | SOPS + age |
| Agents | LangGraph + your own MCP servers | Custom state machine |
| Broker abstraction | Custom canonical model + adapters | CCXT (crypto cold path only) |

**Do not use a third-party all-in-one platform as your core** if you're serious. They're excellent for learning and for prototyping, but you cannot control the fill model, the cost model, or the lookahead guarantees — which is to say you cannot control the three things that determine whether your backtest means anything.

### Realistic budget, per month

| | Lean (Tier 1–2) | Serious (Tier 2) | Tier 3 |
|---|---|---|---|
| Data | ₹5–25k (India EOD + options) | ₹50k–2L (+ US, crypto history) | ₹5L+ (OPRA, tick, PIT fundamentals) |
| Compute | ₹5–15k (cloud VMs) | ₹30–80k | ₹3L+ (bare metal, co-lo) |
| Tools/vendors | ₹5k | ₹20–50k | ₹1L+ |
| **Total** | **₹15–45k/mo** | **₹1–3L/mo** | **₹10L+/mo** |

Tier 3 economics only work above roughly ₹10–20 crore of deployed capital. Below that, spend the money on better data instead — the returns are far higher.

---

## Part VI — 18-month timeline with gates

| Month | Deliverable | Gate to pass |
|---|---|---|
| 1 | Compliance memo, `mandate.yaml`, broker accounts, static IP | Written sign-off per market |
| 2–3 | Security master + India EOD ingest + quality DAG | Zero unmapped instruments for 10 straight days; full rebuild from landing verified |
| 3–4 | Bitemporal API, corp-actions engine | Lookahead test suite cannot break the API; adjusted series matches reference exactly |
| 4–5 | Research env, feature library, IC harness | 30 features with tear sheets in <2 min each |
| 5–7 | Tier A + Tier B backtesters | Known-alpha recovery; zero-alpha = exact cost drag; costs match real contract notes |
| 7–8 | Overfitting battery + promotion gate | ≥3 of your favourite ideas killed by the gate |
| 8–9 | First strategy through the full gauntlet | Passes on locked holdout, unlocked once |
| 9–11 | OMS/EMS + first broker adapter + kill switches | Chaos tests pass; panic button flattens in <10s |
| 11–12 | Paper trading + reality-gap attribution | Residual attribution <10% of PnL over a month |
| 12–13 | **First micro-live capital (1–2%)** | 1 month, zero ops incidents, live/backtest Sharpe > 0.6 |
| 13–14 | India options stack: surfaces, greeks, SPAN, expiry mechanics | Margin model matches broker to <2%; one expiry survived cleanly |
| 14–15 | Portfolio allocator, risk overlay, multi-strategy | 3 live strategies, correlation monitored, allocator backtested |
| 15–16 | US market: second broker, multi-currency, PIT fundamentals | US strategy live at micro size; zero strategy-layer changes needed |
| 16–17 | Agent layer: Scout, Specifier, Coder, Critic, Orchestrator | 20 pre-registered hypotheses/month; Critic catches ≥80% of planted flaws |
| 17–18 | Crypto: 24/7 ops, funding carry, sub-accounts | 30 days unattended weekend operation with no incidents |
| 18+ | Scale capital, FX, latency work if justified by measurement | Each per its own gate |

Slippage is normal. **Do not compress the gates to hit the dates** — the dates are estimates, the gates are the product.

---

## Part VII — Pre-mortem: how this fails

Written now, so you recognise it later.

1. **Data defect masquerading as alpha.** Most common single cause. Mitigation: cross-vendor reconciliation, no-arb checks, bitemporal storage. *If a new strategy shows Sharpe > 3, assume a data bug until proven otherwise — this instinct is worth more than any test.*
2. **Silent lookahead.** A shifted index, a vendor backfill, `.rolling()` without `closed='left'`. Mitigation: the `as_of` firewall enforced at the data layer, plus the timestamp-shift stress test, plus a static lookahead lint in CI.
3. **Costs modelled optimistically.** Especially India: STT on option exercise, freeze quantities, no cash shorting without SLB, crypto TDS. Mitigation: reproduce real contract notes line-by-line; test at 3× costs.
4. **Backtest/live code divergence.** Two implementations always drift. Mitigation: one strategy object, injected adapters, shadow reconciliation nightly.
5. **Regime change invalidating history.** India's derivatives market in 2026 is structurally different from 2023. Mitigation: weight recent data, test regime subsamples, monitor exchange circulars as a data source.
6. **Overfitting via undeclared search.** You ran 4,000 configs and reported one. Mitigation: automatic tamper-evident trial counting, DSR, PBO, locked holdout.
7. **Operational loss dwarfing alpha.** A duplicated order, an unhandled `UNKNOWN` state, a stale-feed trade. Mitigation: idempotent client IDs, reconciliation, four independent kill-switch layers, chaos testing. *Realistically this is where the money actually goes.*
8. **Position-sizing blowup.** Correct signal, wrong size. Mitigation: fractional Kelly, vol targeting, hard limits, correlation monitoring.
9. **Complexity collapse.** You build so much infrastructure you never trade. Mitigation: get one strategy live at micro size by month 13, even if the platform is 40% built. The feedback from live trading redirects your engineering effort more efficiently than any amount of planning.
10. **Automating the accelerator without the brake.** An autonomous research pipeline that can start strategies but not stop them is a machine for accumulating undetected failures. Mitigation: automate the kill rules *first*, before the promotion pipeline.
11. **Agent-driven overfitting at scale.** The specific new risk of this design: an LLM pipeline can generate and test 10,000 hypotheses a month, which means the multiple-testing problem grows by three orders of magnitude. Mitigation: trial counting is not optional, and DSR thresholds must scale with declared trials. AI throughput without AI-proof statistics is a faster route to losing money.
12. **Regulatory non-compliance.** Static-IP lapse, OPS threshold breach, missing Algo-ID, unregistered strategy above threshold. Mitigation: hard OPS governor in the EMS, compliance checks in pre-trade risk, quarterly review against current circulars.

---

## Appendix — Definition of done, per layer

**Data:** rebuildable from raw landing; bitemporal; quality-gated; corp-action-correct; zero unmapped symbols; cross-vendor reconciled.
**Research:** every experiment reproducible from `(git_sha, config_hash, dataset_version)`; failures logged to the graveyard as diligently as successes.
**Backtest:** invariants asserted per event; recovers planted alpha; zero-alpha yields exact modelled cost; golden-file regression in CI; determinism verified.
**Validation:** pre-registered; CPCV distribution reported not a point estimate; DSR/PBO computed with declared trial count; holdout read exactly once.
**Execution:** idempotent; reconciled continuously; state machine persisted; every order tagged with strategy/sha/config/Algo-ID; four kill-switch layers tested.
**Risk:** every limit expressible in one config file, enforced in a separate process, tested by deliberate breach in staging.
**Ops:** deployable by IaC from zero; observable with alerts that page only for money-at-risk; runbook for every past incident; game day passed this month.
**Agents:** no prod credentials; all output through the same CI; trial counter tamper-evident; Critic eval catch-rate measured and tracked.

---

### One-line summary

Build the **data firewall** and the **kill switch** first, the **promotion gate** second, the **strategies** third, and the **agents** last — because the agents multiply whatever you point them at, and if you point 100× throughput at a leaky validation process, you will lose money 100× faster.
