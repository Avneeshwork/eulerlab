# 079 — What NautilusTrader and other platforms have that this one does not, and a live risk screen

**Question.** Operator, 2026-10-14: "look over Nautilus Trader and other
platforms and let me know what features are missing on our platform", and "a
screen which shows risk on current trading strategies: current VaR, strategy
distribution, maximum risk, allocation in different strategies ... research
on it first and then make a mockup".

**Nothing was built for this note.** It is a comparison, a specification for
the screen, and a mockup with sample numbers.

## Sources, fetched 2026-10-14

| Source | URL | Read |
|---|---|---|
| NautilusTrader, concepts: overview | https://nautilustrader.io/docs/latest/concepts/overview/ | Page, through an automatic summary |
| NautilusTrader, concepts: architecture | https://nautilustrader.io/docs/latest/concepts/architecture/ | Same |
| NautilusTrader, concepts: portfolio | https://nautilustrader.io/docs/latest/concepts/portfolio/ | Same |
| NautilusTrader, concepts: execution | https://nautilustrader.io/docs/latest/concepts/execution/ | Same |
| QuantConnect, supported risk management models | https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/risk-management/supported-models | Same |
| QuantConnect, live trading results | https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/results | Same |
| QuantConnect, backtest report | https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/report | Same |
| OpenAlgo, documentation home | https://docs.openalgo.in/ | Same |
| What a multi-strategy risk view shows | one web search; practitioner pages and vendor blogs, e.g. https://interactivebrokers.co.uk/en/software/tws.bak/usersguidebook/priceriskanalytics/risk_navigator_dashboard.htm | **Search summary only.** No regulator or industry-body source was read |

Every page was read through the fetch tool's summary, not line by line. Not
read: NautilusTrader's API reference (the full list of built-in statistics
and the risk engine's default limits), its adapters list, and any pricing or
licence page. Streak, Composer and Interactive Brokers' Risk Navigator were
not opened.

## What they have that this platform does not

Marked by how much it matters for one operator trading Indian markets from
daily closes, with no live capital yet.

### Matters now

| Missing here | Who has it | Why it matters |
|---|---|---|
| **A portfolio view across deployments**: total equity, net and gross exposure, realised and unrealised P&L in one place | NautilusTrader `Portfolio`; QuantConnect's runtime banner | Three paper deployments run today and each is shown on its own. Nothing adds them up |
| **Any risk number**: VaR, expected shortfall, volatility, beta to the Nifty | QuantConnect reports rolling beta and leverage; VaR is the common language of every desk view found | The kill switch counts orders and rupees per name. Nothing says how much the book could lose tomorrow |
| **Exposure over time, and concentration** by name and sector | QuantConnect: exposure and asset-allocation charts, a sector-exposure cap | The two momentum deployments hold the same strategy. Overlap is invisible |
| **Limits with headroom**: how much of each limit is used | Found in every desk description; NautilusTrader checks notional and rate before each order | The Live & Risk page lists what trips the switch, not how close it is |
| **A "reduce only" state** between trading and stopped | NautilusTrader: `ACTIVE`, `REDUCING`, `HALTED` | The kill switch here is on or off. A deployment in trouble cannot be told to only close positions |
| **Drawdown rules that act**: stop a strategy or the book at a loss limit | QuantConnect: per-security and portfolio drawdown models, trailing stop | Deployments halt on broken books and unresolved orders, never on a loss |
| **Backtest drawn against live**: the expected path beside the realised one | QuantConnect draws the out-of-sample backtest over the live curve | Section 6.7 measures the reality gap as a number; no screen shows it per deployment |

### Matters when live trading starts (T-4022)

| Missing here | Who has it |
|---|---|
| A proven live broker link, with reconciliation that de-duplicates fills | NautilusTrader; OpenAlgo with 36 broker plugins |
| Order types beyond a market order at the close: limit, stop, trailing, bracket, OCO | NautilusTrader |
| Execution algorithms (TWAP) to work a large order | NautilusTrader |
| Margin by instrument, and a margin-used chart | NautilusTrader; QuantConnect |
| Manual order approval before anything is sent | OpenAlgo's Action Center |
| Order events drawn on the price chart | QuantConnect's asset plot |
| Latency and traffic logs for the broker link | OpenAlgo |

### Does not matter here, or not yet

| Missing here | Who has it | Why not |
|---|---|---|
| Tick and order-book data, nanosecond simulation | NautilusTrader | Every strategy here trades closes or minute bars |
| Volume, dollar and imbalance bars | NautilusTrader | No strategy asks for them |
| Many venues at once, market-making | NautilusTrader | One broker, one operator |
| A Rust core for speed | NautilusTrader | The slow part here is reading data, not the engine |
| Portfolio construction models (mean-variance, risk parity) | QuantConnect | Deployments are sized by hand (ADR-060) |
| Webhooks from TradingView, Amibroker, ChartInk | OpenAlgo | Signals here come from the platform's own strategies |
| A no-code flow builder with 61 node types | OpenAlgo | The strategy builder covers rules; no demand for more |

## What this platform has that they do not

Stated because a list of gaps alone reads as "behind". None of the three
sources describes: a trial ledger that counts every configuration tried and
raises the bar for the next; a promotion gate with deflated Sharpe, PBO and
minimum backtest length; a holdout read exactly once; point-in-time data with
two clocks; itemised Indian costs by segment and date; or a research library
that keeps each paper beside the result of testing it. Those are about not
fooling yourself before trading. The gaps above are about seeing and
controlling risk while trading.

## The risk screen: what it should show

One page, "Risk", read top to bottom, for all active deployments together and
then each one.

1. **The book in one line.** Capital deployed, equity, today's and total
   P&L, net and gross exposure, cash, VaR and expected shortfall for one day.
2. **VaR.** One-day 95% and 99% VaR and expected shortfall, in rupees and as
   a percentage of equity. Shown beside the distribution of daily P&L it comes
   from, with the worst day marked. Three methods side by side when they
   disagree: historical, parametric, and Monte Carlo (section 5.6a exists).
3. **Where the risk is.** Each strategy's share of capital beside its share
   of VaR. A strategy with 20% of capital and 40% of the VaR is the finding.
4. **Allocation.** By strategy, by instrument and by sector, with the
   largest single name called out, and the overlap between deployments.
5. **Limits and headroom.** Every limit as a bar: used, limit, and what
   happens when it trips. Includes the limits that exist (orders a day,
   notional per name, unresolved orders) and the ones proposed below.
6. **Drawdown.** Current drawdown for the book and each deployment against
   the worst its backtest saw.
7. **Stress.** What the current positions would lose in named scenarios:
   Nifty -5% and -10%, March 2020, a gap down at the open, India VIX doubling.
8. **Live against backtest.** Each deployment's realised curve inside the
   band its backtest predicted.
9. **Per-deployment table.** Capital, equity, P&L, volatility, VaR, beta to
   the Nifty, drawdown, positions, days live, state.

### Definitions the screen needs, and what would have to be decided

- **VaR** at 95% for one day: the loss exceeded on one day in twenty.
  **Expected shortfall**: the average loss on those days.
- **Component VaR**: a strategy's contribution to the book's VaR, summing to
  the total. It needs the correlation between deployments.
- **The history is the problem.** The deployments are 5 to 13 days old.
  A VaR from 13 daily returns is not a number. The honest construction is to
  apply each deployment's *current positions* to the last 250 days of prices
  held in the panel. That is a new calculation, and its assumptions (window,
  confidence, how a future is treated) belong in an ADR before any code.
- **New limits are the operator's.** A loss limit per day, a drawdown limit
  per deployment and a VaR limit for the book do not exist. `killswitch.yaml`
  is operator-owned in spirit, like `mandate.yaml`: proposing values is in
  scope, setting them is not.

## Decision

A mockup of the screen is published with **sample numbers**; it is a design,
not a reading of the paper books: https://claude.ai/artifact/BzV78BRUdaZSx1PYYC2cFB
(three screens: overview, performance by deployment, stress and exposure;
private to the operator's account). Building it is three pieces of work, in
this order: the portfolio roll-up across deployments, the VaR calculation
from current positions, then the limits with headroom.

**Confidence:** high on what this platform lacks; it is read from its own
code. Moderate on the other platforms: summaries of documentation pages, and
NautilusTrader's risk engine defaults were not found.
