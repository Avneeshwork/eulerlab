"""Reconciliation: the broker is right, and we find out how we were wrong.

`CLAUDE.md`: *The broker is the source of truth. Local position state is a
cache.*

Taking that literally has one consequence that people flinch at, so it is
worth being explicit. When the two disagree, **the fix is always to the local
record, never to the market.** The reconciler will happily rewrite what we
think we hold. It will never place an order to make the broker's position
match our belief, and there is no flag to make it do so.

The reason is that a break means we do not know what happened. Maybe a fill
arrived that we missed. Maybe an order we thought was dead was live. Maybe
there was a corporate action, or a manual trade in the broker's app. Trading
to "correct" the difference acts on the one thing we have just established we
are wrong about, and it doubles the position exactly when the cause is a fill
we failed to record. So the reconciler produces a report, and a human decides
whether any trade follows.

Four kinds of break, in descending order of how much they should worry you:

- **`broker_only`** — a position at the broker we have no record of. The worst
  one: unmanaged risk, invisible to every stop and every limit in this system.
- **`quantity`** — both sides know the symbol and disagree on size. Usually a
  missed partial fill.
- **`local_only`** — we think we hold something the broker does not. Usually an
  order we recorded as filled that was actually rejected.
- **`unknown_order`** — an order working at the broker that we did not send, or
  did send and forgot. It can still fill, which makes it a live liability
  rather than a bookkeeping note.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eulerlab.costs.schedule import Side
from eulerlab.oms.broker import BrokerAdapter
from eulerlab.oms.oms import OMS

SEVERITY = {"broker_only": 0, "quantity": 1, "local_only": 2, "unknown_order": 3}


@dataclass(frozen=True)
class Break:
    kind: str
    symbol: str
    local: int
    broker: int
    detail: str = ""

    def line(self) -> str:
        return f"  {self.kind:<14} {self.symbol:<14} local {self.local:>8}   broker {self.broker:>8}   {self.detail}"


@dataclass
class Reconciliation:
    matched: list[str] = field(default_factory=list)
    breaks: list[Break] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.breaks

    def render(self) -> str:
        lines = ["", "reconciliation — the broker is the source of truth", ""]
        lines.append(f"  {len(self.matched)} position(s) agree")
        if not self.breaks:
            lines.append("  no breaks")
            return "\n".join(lines)
        lines.append("")
        for item in sorted(self.breaks, key=lambda b: (SEVERITY.get(b.kind, 9), b.symbol)):
            lines.append(item.line())
        lines.append(
            "\nThe local record is what gets corrected. No order is placed to make the\n"
            "broker agree with us: a break means we do not know what happened, and\n"
            "trading on that is how a missed fill becomes a doubled position."
        )
        return "\n".join(lines)


def local_positions(oms: OMS) -> dict[str, int]:
    """What our own journal says we hold.

    Derived from the journal's fills rather than kept as a running total, so
    the comparison is against the record we would actually have after a
    restart — which is the state that has to be right.
    """
    out: dict[str, int] = {}
    for execution in oms.executions():
        signed = execution.quantity if execution.side is Side.BUY else -execution.quantity
        out[execution.symbol] = out.get(execution.symbol, 0) + signed
    return {symbol: qty for symbol, qty in out.items() if qty}


def reconcile(oms: OMS, adapter: BrokerAdapter | None = None) -> Reconciliation:
    """Compare and report. Changes nothing."""
    broker = adapter or oms.adapter
    ours = local_positions(oms)
    theirs = broker.positions()
    result = Reconciliation()

    for symbol in sorted(set(ours) | set(theirs)):
        mine = ours.get(symbol, 0)
        yours = theirs.get(symbol, 0)
        if mine == yours:
            result.matched.append(symbol)
            continue
        if mine == 0:
            result.breaks.append(
                Break(
                    "broker_only",
                    symbol,
                    mine,
                    yours,
                    "a position we are not managing — no stop, no limit applies to it",
                )
            )
        elif yours == 0:
            result.breaks.append(
                Break(
                    "local_only", symbol, mine, yours, "we think we hold this; the broker does not"
                )
            )
        else:
            result.breaks.append(
                Break("quantity", symbol, mine, yours, f"out by {yours - mine:+d} shares")
            )

    known = set(oms.states())
    for view in broker.open_orders():
        if view.client_order_id not in known:
            result.breaks.append(
                Break(
                    "unknown_order",
                    view.client_order_id,
                    0,
                    view.filled_quantity,
                    f"working at the broker as {view.broker_order_id}; we never sent it",
                )
            )
    return result
