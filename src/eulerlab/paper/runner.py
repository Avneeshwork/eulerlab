"""Paper trading: the same run, with a broker in the middle.

There is no paper-trading loop. There is `event_driven.run` with a different
executor plugged into it — `OMSExecutor` instead of `SimulatedExecutor` — and
that is the entire difference between a backtest and a paper run.

What that buys is worth being precise about. Every order in a paper run is
built by the same `plan_orders` call, carries the same deterministic client
order id, and updates the same `Portfolio` object as in the backtest. So when
the two produce different equity curves, the difference cannot be a bug in
"the paper version of the sizing logic", because there is no paper version of
the sizing logic. It is the broker, or the costs, or a rejection. That is what
makes the attribution in `attribution.py` a measurement rather than a guess.

**Costs are computed here, by us, not reported by the broker.** In paper mode
that is the only option — a simulator has no contract note — and it is worth
naming as a limitation rather than a feature: the cost component of the
reality gap is currently zero *by construction*, and stays zero until a real
broker's charges can be compared against the model. T-906 (reconciling
against twenty real contract notes) is the thing that would give that number
meaning.

The kill switch is not caught here. If it trips mid-run the exception
propagates and the run stops, which is the correct behaviour for a thing whose
entire purpose is to stop trading.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from eulerlab.backtest import event_driven, vector
from eulerlab.backtest.events import Fill, Order, Rejection
from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import Strategy
from eulerlab.costs.model import Brokerage
from eulerlab.costs.schedule import Side
from eulerlab.features.library import BY_NAME
from eulerlab.features.panel import PanelRow, read_panel
from eulerlab.oms import ems, reconcile
from eulerlab.oms.journal import Journal
from eulerlab.oms.killswitch import KillSwitch
from eulerlab.oms.oms import OMS, Execution
from eulerlab.oms.paper_broker import PaperBroker, PaperFaults
from eulerlab.oms.states import OrderState

PAPER_DIR = Path("data/oms/paper")


class OMSExecutor:
    """Route the order through the order manager and report what came back.

    Note what this does *not* do: it does not decide anything. It does not
    retry, does not resize, does not skip an order it dislikes. Every one of
    those would be a decision the backtest never made, and would show up in
    the reality gap as unexplained residual — attributed to the market when it
    was really attributable to us.
    """

    name = "oms"

    def __init__(
        self,
        oms: OMS,
        *,
        asset_class: str,
        brokerage: Brokerage | None = None,
        fund_symbols: frozenset[str] = frozenset(),
    ) -> None:
        self.oms = oms
        self.asset_class = asset_class
        self.brokerage = brokerage
        self.fund_symbols = fund_symbols
        self.submitted = 0
        self.rejected = 0
        self.resolved_after_timeout = 0

    def execute(self, order: Order, *, day: date, price: float | None) -> Fill | Rejection:
        self.submitted += 1
        if price is None or price <= 0:
            # No price means there is nothing to send. Rejected without
            # touching the broker, in the same words the simulated executor
            # uses, so this case cannot become a difference between them.
            self.rejected += 1
            return Rejection(order.client_order_id, day, order.symbol, "no trade on fill day")

        state = self.oms.submit(order, price=price)
        if state is OrderState.UNKNOWN:
            # An ambiguous send, right now, mid-run. The rule is that UNKNOWN
            # is resolved by asking — and the moment to ask is immediately,
            # not at the next startup. Waiting would leave a possibly-live
            # order unaccounted for while the strategy keeps sending more on
            # top of it, which is how one bad send becomes a bad session.
            self.oms.resolve_unknown()
            self.resolved_after_timeout += 1
            state = self.oms.state(order.client_order_id) or OrderState.UNKNOWN

        if state is not OrderState.FILLED:
            self.rejected += 1
            return Rejection(
                order.client_order_id, day, order.symbol, f"broker: order is {state.value}"
            )

        execution = self._execution_for(order.client_order_id)
        if execution is None:
            self.rejected += 1
            return Rejection(
                order.client_order_id, day, order.symbol, "filled but no execution recorded"
            )
        cost = vector._costs_for(
            day,
            execution.price,
            execution.quantity,
            order.side,
            self.brokerage,
            self.asset_class,
            fund_unit=order.symbol in self.fund_symbols,
        )
        return Fill(
            client_order_id=order.client_order_id,
            day=day,
            symbol=order.symbol,
            side=order.side,
            quantity=execution.quantity,
            price=execution.price,
            cost=cost,
        )

    def _execution_for(self, client_order_id: str) -> Execution | None:
        """The fill the OMS recorded, read back from the journal.

        Read back rather than taken from the broker's reply, so the number the
        portfolio uses is the number that was written down. If those two ever
        differ, the accounting follows the record, which is what an audit
        would check against.
        """
        for entry in reversed(self.oms.journal.history(client_order_id)):
            quantity = entry.detail.get("filled_quantity")
            price = entry.detail.get("average_price")
            if not quantity or not price:
                continue
            return Execution(
                client_order_id=client_order_id,
                symbol=str(entry.detail["symbol"]),
                side=Side(str(entry.detail["side"])),
                quantity=int(quantity),
                price=float(price),
                day=date.fromisoformat(str(entry.detail["signal_day"])),
            )
        return None


@dataclass
class PaperRun:
    result: event_driven.TierBResult
    executor: OMSExecutor
    oms: OMS
    reconciliation: reconcile.Reconciliation

    def render(self) -> str:
        portfolio = self.result.portfolio
        lines = [
            "",
            f"paper run — {self.result.strategy}",
            "",
            f"  days              {len(self.result.days):,}",
            f"  orders submitted  {self.executor.submitted:,}",
            f"  filled            {len(self.result.fills):,}",
            f"  rejected          {len(self.result.rejections):,}",
            f"  timeouts resolved {self.executor.resolved_after_timeout:,}",
            f"  final equity      Rs {self.result.final_equity:,.2f}",
            f"  total return      {self.result.total_return:+.2%}",
            f"  costs paid        Rs {self.result.total_cost:,.2f}",
        ]
        if portfolio:
            lines.append(f"  positions held    {len(portfolio.holdings()):,}")
        lines.append(f"  unresolved orders {len(self.oms.unresolved())}")
        lines.append(self.reconciliation.render())
        return "\n".join(lines)


def fresh_oms(
    root: Path = PAPER_DIR,
    *,
    slippage_bps: float = 0.0,
    faults: PaperFaults | None = None,
) -> OMS:
    """A paper OMS rooted in its own directory, with its own kill switch.

    Its own switch, not the live one. A paper experiment must never be able to
    halt live trading, and a tripped live switch must never silently stop a
    paper experiment either. They are different systems that share code.
    """
    root.mkdir(parents=True, exist_ok=True)
    return OMS(
        PaperBroker(root / "paper_broker.json", slippage_bps=slippage_bps, faults=faults),
        journal=Journal(root / "orders.jsonl"),
        governor=ems.Governor(),
        kill_switch=KillSwitch(root / "KILL_SWITCH", root / "killswitch_log.jsonl"),
    )


def run(
    rows: Sequence[PanelRow],
    strategy: Strategy,
    *,
    oms: OMS,
    rebalance: int = 21,
    starting_cash: float = 1_000_000.0,
    warmup: int = 253,
    # The venue this account trades on. Defaulted here and nowhere deeper:
    # paper trading is NSE-only today, and this is the *account's* property
    # rather than a guess about the data — which is the distinction that makes
    # a default safe here and unsafe at every level below.
    asset_class: str = "equity",
    brokerage: Brokerage | None = None,
    adjusted_index: dict[str, dict[date, float]] | None = None,
) -> PaperRun:
    """One paper run. Recovery first, then trade.

    Recovery before anything is sent, always. Starting a session with orders
    in an unknown state and sending more on top is how a bad morning becomes a
    bad week.
    """
    oms.recover()
    executor = OMSExecutor(
        oms, brokerage=brokerage, asset_class=asset_class, fund_symbols=vector.fund_symbols(rows)
    )
    result = event_driven.run(
        rows,
        strategy,
        asset_class=asset_class,
        starting_cash=starting_cash,
        rebalance_every=rebalance,
        warmup=warmup,
        brokerage=brokerage,
        adjusted_index=adjusted_index,
        executor=executor,
    )
    # One more sweep at the end. Anything still UNKNOWN here could not be
    # resolved even on a retry, which means the session is finishing with
    # orders that may be live — the single most important thing for the report
    # to say out loud.
    oms.resolve_unknown()
    return PaperRun(
        result=result,
        executor=executor,
        oms=oms,
        reconciliation=reconcile.reconcile(oms),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a strategy through the OMS in paper mode.")
    parser.add_argument("--feature", default="momentum_12_1")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--rebalance", type=int, default=21)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--days", type=int, default=0, help="use only the last N trading days")
    parser.add_argument("--reset", action="store_true", help="start from an empty journal")
    args = parser.parse_args(argv)

    if args.feature not in BY_NAME:
        print(f"unknown feature {args.feature!r}; try one of {sorted(BY_NAME)}")
        return 2

    if args.reset:
        for name in ("orders.jsonl", "paper_broker.json", "KILL_SWITCH"):
            (PAPER_DIR / name).unlink(missing_ok=True)

    rows = read_panel()
    if not rows:
        print("no panel. Run `make build-panel` first.")
        return 2
    if args.days:
        cutoff = sorted({r.day for r in rows})[-args.days :][0]
        rows = [r for r in rows if r.day >= cutoff]

    strategy = RankAndHold(BY_NAME[args.feature], top_n=args.top_n)
    oms = fresh_oms(slippage_bps=args.slippage_bps)
    outcome = run(rows, strategy, oms=oms, rebalance=args.rebalance)
    print(outcome.render())
    print(
        "\nThis is a simulated broker. It is not evidence about live execution —\n"
        "it is evidence that the order path works and that the accounting closes."
    )
    return 0 if outcome.reconciliation.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
