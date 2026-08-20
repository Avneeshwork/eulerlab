# ADR-031 — Paper trading is the backtest loop with a different executor

**Context.** Sprints 25–28 need a paper-trading system whose results can be
compared against the backtest that authorised the strategy.

**Options.** (a) Write a paper-trading loop that walks days, asks the strategy
for weights and sends orders. (b) Extract the fill step of `event_driven.run`
into an `Executor` and swap it.

**Choice.** (b). `SimulatedExecutor` fills at the engine's price;
`OMSExecutor` sends through the order manager to a broker. Everything else —
the market view, the weights, `plan_orders`, the `Portfolio` — is one code
path.

**Why.** (a) is a copy of the engine, and copies drift. The reality-gap report
exists to explain differences between paper and backtest; if the two loops can
differ for reasons of their own, that report measures our bugs rather than the
market. With (b) the difference is *provably* the executor: a frictionless
paper run reproduces the backtest to the paisa, and
`tests/test_paper_attribution.py` asserts exact equality rather than
approximate agreement.

**Cost if wrong.** The `Executor` protocol is narrow — one order, one day, one
price. A venue needing richer interaction (working an order over hours,
responding to partial fills) will need it widened, and widening it is where
the two paths could start to diverge again.
