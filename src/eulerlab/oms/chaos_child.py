"""A process that dies on purpose, at a chosen point in the order lifecycle.

Run as a subprocess by `chaos.py` and `SIGKILL`ed from inside itself. `SIGKILL`
rather than an exception or `sys.exit`, because those unwind: `finally` blocks
run, buffers flush, context managers close. A power cut does none of that, and
a crash test that lets the process tidy up is testing the tidy-up path.

Killing itself rather than being killed by the parent removes the race. The
parent cannot know when the child is between the journal write and the send;
the child knows exactly.
"""

from __future__ import annotations

import argparse
import os
import signal
from datetime import date
from pathlib import Path

from eulerlab.backtest.events import Order, client_order_id
from eulerlab.costs.schedule import Side
from eulerlab.oms.journal import Journal
from eulerlab.oms.paper_broker import PaperBroker
from eulerlab.oms.states import Event, OrderState

STRATEGY = "chaos"
SYMBOL = "RELIANCE"
SIGNAL_DAY = date(2026, 8, 20)
QUANTITY = 10
PRICE = 1234.5
SEQ = 1


def the_order() -> Order:
    """The one order every scenario uses. Deterministic, so the parent can
    name it without the child telling it anything."""
    return Order(
        client_order_id=client_order_id(STRATEGY, SIGNAL_DAY, SYMBOL, SEQ),
        strategy_id=STRATEGY,
        signal_day=SIGNAL_DAY,
        symbol=SYMBOL,
        side=Side.BUY,
        quantity=QUANTITY,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["after-intent", "after-place"])
    parser.add_argument("--dir", required=True)
    args = parser.parse_args(argv)

    root = Path(args.dir)
    journal = Journal(root / "orders.jsonl")
    broker = PaperBroker(root / "paper_broker.json")
    order = the_order()

    journal.append(
        order.client_order_id,
        Event.CREATED,
        OrderState.INTENT,
        {
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "strategy_id": order.strategy_id,
            "signal_day": order.signal_day.isoformat(),
        },
    )

    if args.mode == "after-intent":
        # Dead between the journal write and the network call. The broker has
        # never heard of this order.
        os.kill(os.getpid(), signal.SIGKILL)

    broker.place(order, price=PRICE)
    # Dead between the send and recording what came back. The order is live at
    # the broker and our journal still says INTENT.
    os.kill(os.getpid(), signal.SIGKILL)
    return 0  # unreachable, and that is the point


if __name__ == "__main__":
    raise SystemExit(main())
