"""The order manager: submit once, recover honestly, resolve by asking.

Three properties, each of which is a rule from `CLAUDE.md` made structural
rather than remembered.

**Submitting the same order twice does nothing the second time.** The client
order id is `hash(strategy_id, signal_time, instrument_id, seq)`, so the same
intention always produces the same id. `submit` looks it up in the journal
first and returns the state it already has. A retry after a timeout, a
re-run of the same rebalance, a script started twice — none of them can
double-send. And the defence is two-deep: even if the OMS somehow sent again,
the broker rejects a duplicate client order id, and `ems.send` reads that
rejection as *the original is fine* rather than as a failure. (Kite does not
enforce unique tags, so on Kite only the journal lookup stands; T-4328.)

**Intent is on disk before the network call.** `submit` journals `INTENT`,
fsynced, and only then sends. There is no window in which an order exists at
the broker and not in our records.

**Recovery asks; it never assumes.** On startup every non-terminal order moves
to `UNKNOWN`, because whatever happened while this process was dead is not
knowable from local state. Each one is then resolved by querying the broker.
If the query fails, the order stays `UNKNOWN` — there is no timeout after
which it is written off, because writing it off is the assumption the rules
forbid.

One case gets special handling and it is worth naming. If the broker reports
no knowledge of an order **that we have recorded fills for**, that is not a
resolution, it is a contradiction: one of the two records is wrong, and
quietly picking the broker's would erase a position we are actually holding.
The OMS refuses to resolve it and reports it as a break for a human.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from eulerlab.backtest.events import Order
from eulerlab.costs.schedule import Side
from eulerlab.oms import ems
from eulerlab.oms.broker import BrokerAdapter, BrokerOrderView, BrokerUnreachable
from eulerlab.oms.journal import Journal, JournalEntry
from eulerlab.oms.killswitch import KillSwitch, KillSwitchTripped
from eulerlab.oms.states import Event, OrderState, is_terminal, transition

FILL_EVENTS = frozenset(
    {Event.FILL, Event.PARTIAL_FILL, Event.QUERY_FOUND_FILLED, Event.QUERY_FOUND_PARTIAL}
)


@dataclass(frozen=True)
class Execution:
    """A fill as the OMS knows it: no cost, because that is not its job.

    Costs are applied by whoever owns the portfolio, using the same cost model
    the backtest uses. Two cost paths is the divergence `CLAUDE.md` warns
    about, and an OMS that prices its own fills is how the second one starts.
    """

    client_order_id: str
    symbol: str
    side: Side
    quantity: int
    price: float
    day: date


@dataclass
class ResolutionReport:
    """The result of asking the broker about everything we are unsure of."""

    resolved: dict[str, OrderState] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    breaks: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.unresolved and not self.breaks

    def render(self) -> str:
        lines = ["", "resolution", ""]
        for coid, state in sorted(self.resolved.items()):
            lines.append(f"  resolved   {coid}  ->  {state.value}")
        for coid in self.unresolved:
            lines.append(f"  UNRESOLVED {coid}  broker could not be asked; still UNKNOWN")
        for detail in self.breaks:
            lines.append(f"  BREAK      {detail}")
        if not (self.resolved or self.unresolved or self.breaks):
            lines.append("  nothing to resolve")
        return "\n".join(lines)


class OMS:
    """Owns the journal. Everything that touches an order goes through here."""

    def __init__(
        self,
        adapter: BrokerAdapter,
        *,
        journal: Journal | None = None,
        governor: ems.Governor | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self.adapter = adapter
        self.journal = journal or Journal()
        self.governor = governor or ems.Governor()
        self.kill_switch = kill_switch or KillSwitch()

    # --- reading ------------------------------------------------------------

    def states(self) -> dict[str, OrderState]:
        return self.journal.replay()

    def state(self, client_order_id: str) -> OrderState | None:
        return self.states().get(client_order_id)

    def in_flight(self) -> dict[str, OrderState]:
        return {c: s for c, s in self.states().items() if not is_terminal(s)}

    def unresolved(self) -> list[str]:
        return sorted(c for c, s in self.states().items() if s is OrderState.UNKNOWN)

    def executions(self) -> list[Execution]:
        """Every fill, rebuilt from the journal, one per order.

        From the journal rather than from an in-memory list, so a process that
        just started has exactly the same view as one that has been running all
        day. An OMS whose answer depends on its own uptime is not a record.

        A fill entry carries the broker's **cumulative** filled quantity and
        average price (Kite's `filled_quantity` is cumulative), so the latest
        entry for an order is the whole of it. Until 2026-11-01 every entry was
        summed, so a partial fill seen once and then the complete fill seen
        after a restart counted 50 + 100 shares for a 100-share order, and
        reconciliation reported a break that was not there (HISTORY #49).
        """
        latest: dict[str, Execution] = {}
        for entry in self.journal.read():
            if entry.event not in FILL_EVENTS:
                continue
            detail = entry.detail
            quantity = int(detail.get("filled_quantity", 0))
            if quantity <= 0:
                continue
            # Re-inserting keeps the order's first-fill position in the dict.
            latest[entry.client_order_id] = Execution(
                client_order_id=entry.client_order_id,
                symbol=str(detail["symbol"]),
                side=Side(detail["side"]),
                quantity=quantity,
                price=float(detail["average_price"]),
                day=date.fromisoformat(str(detail["signal_day"])),
            )
        return list(latest.values())

    def _has_fills(self, client_order_id: str) -> bool:
        return any(e.event in FILL_EVENTS for e in self.journal.history(client_order_id))

    # --- writing ------------------------------------------------------------

    def _apply(
        self,
        client_order_id: str,
        current: OrderState,
        event: Event,
        detail: dict[str, object] | None = None,
    ) -> OrderState:
        new_state = transition(current, event)
        self.journal.append(client_order_id, event, new_state, detail or {})
        return new_state

    def submit(self, order: Order, *, price: float | None = None) -> OrderState:
        """Place one order, at most once, ever.

        Returns the order's state afterwards. Raises only for conditions that
        must stop the whole batch — a tripped kill switch or a rate limit that
        cannot be waited out. A broker rejection is not one of those: it is a
        normal outcome, recorded and returned.
        """
        existing = self.state(order.client_order_id)
        if existing is not None:
            # Already known. Do not journal, do not send, do not "just check".
            return existing

        intent_detail: dict[str, object] = {
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "strategy_id": order.strategy_id,
            "signal_day": order.signal_day.isoformat(),
            "algo_id": order.algo_id,
            "price_hint": price,
        }
        self.journal.append(order.client_order_id, Event.CREATED, OrderState.INTENT, intent_detail)
        state = OrderState.INTENT

        try:
            self.kill_switch.require_clear()
        except KillSwitchTripped:
            self._apply(
                order.client_order_id,
                state,
                Event.SEND_REFUSED,
                {"reason": f"kill switch: {self.kill_switch.reason()}"},
            )
            raise

        try:
            waited = self.governor.acquire()
        except ems.RateLimitExceeded as exc:
            self._apply(
                order.client_order_id, state, Event.SEND_REFUSED, {"reason": f"governor: {exc}"}
            )
            raise

        outcome = ems.send(self.adapter, order, price=price)
        detail: dict[str, object] = {
            "broker_order_id": outcome.broker_order_id,
            "detail": outcome.detail,
            "waited_seconds": round(waited, 4),
        }
        state = self._apply(order.client_order_id, state, outcome.event, detail)

        if outcome.event is Event.SEND_OK and price is not None:
            # The paper broker fills at once. A broker that works an order
            # would instead send an ack here and a fill later; the state
            # machine covers both and this call site does not need to care.
            view = self._safe_query(order.client_order_id)
            if view is not None and view.status == "complete":
                state = self._apply(
                    order.client_order_id,
                    state,
                    Event.FILL,
                    {
                        "symbol": order.symbol,
                        "side": order.side.value,
                        "filled_quantity": view.filled_quantity,
                        "average_price": view.average_price,
                        "signal_day": order.signal_day.isoformat(),
                        "broker_order_id": view.broker_order_id,
                    },
                )
        return state

    def _safe_query(self, client_order_id: str) -> BrokerOrderView | None:
        """A query used only to enrich a successful send. Failure is fine here.

        Distinct from `resolve_unknown`, where a failed query has to be
        recorded as unresolved. Here the order's state is already correct;
        this call is only trying to attach fill details to it.
        """
        try:
            return self.adapter.query(client_order_id)
        except BrokerUnreachable:
            return None

    # --- recovery -----------------------------------------------------------

    def recover(self) -> ResolutionReport:
        """Called on every startup, before anything else may send.

        Every order that is not terminal becomes `UNKNOWN` first. That looks
        heavy-handed for an order the journal last saw as `ACKNOWLEDGED`, and
        it is exactly right: `ACKNOWLEDGED` is what we knew *before* the
        process died, and it may have filled, been cancelled, or been rejected
        since. Local state is a cache, and a cache that outlived its process
        is stale by definition.
        """
        for client_order_id, state in sorted(self.in_flight().items()):
            if state is OrderState.UNKNOWN:
                continue
            self._apply(client_order_id, state, Event.PROCESS_RESTART, {"was": state.value})
        return self.resolve_unknown()

    def resolve_unknown(self) -> ResolutionReport:
        """Ask the broker about everything we are unsure of."""
        report = ResolutionReport()
        for client_order_id in self.unresolved():
            try:
                view = self.adapter.query(client_order_id)
            except BrokerUnreachable as exc:
                self._apply(
                    client_order_id, OrderState.UNKNOWN, Event.QUERY_FAILED, {"error": str(exc)}
                )
                report.unresolved.append(client_order_id)
                continue

            if view is None:
                if self._has_fills(client_order_id):
                    # Contradiction, not a resolution. Refuse both readings.
                    report.breaks.append(
                        f"{client_order_id}: we have recorded fills, the broker has no "
                        f"record of the order. One of the two is wrong; a human decides which."
                    )
                    report.unresolved.append(client_order_id)
                    continue
                report.resolved[client_order_id] = self._apply(
                    client_order_id, OrderState.UNKNOWN, Event.QUERY_ABSENT, {}
                )
                continue

            detail: dict[str, object] = {
                "broker_order_id": view.broker_order_id,
                "status": view.status,
                "filled_quantity": view.filled_quantity,
                "average_price": view.average_price,
                "reason": view.reason,
            }
            history = self.journal.history(client_order_id)
            if view.status in {"complete", "partial"} and history:
                detail["symbol"] = history[0].detail.get("symbol")
                detail["side"] = history[0].detail.get("side")
                detail["signal_day"] = history[0].detail.get("signal_day")
            report.resolved[client_order_id] = self._apply(
                client_order_id, OrderState.UNKNOWN, view.event(), detail
            )
        return report

    def history(self, client_order_id: str) -> list[JournalEntry]:
        return self.journal.history(client_order_id)
