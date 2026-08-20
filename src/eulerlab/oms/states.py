"""The order state machine.

`CLAUDE.md`: *An `UNKNOWN` order state is resolved by querying, never by
assuming.*

That single rule is the reason this module is a table and not a set of `if`
statements. An order's state changes only by applying an **event** to it, and
the table decides what each event means. Nothing anywhere can write a state
directly, so "assume it filled" is not a thing a caller can express — there is
no event that means that.

The states worth explaining are the two most people leave out:

**`UNKNOWN` is a real state, not an error.** Every send has three outcomes,
not two: it landed, it did not land, or *we do not know*. A network timeout,
a connection reset, a process killed between the write and the response — all
of these leave a live order that may or may not exist at the broker. Systems
that model two outcomes handle the third by picking one, and picking wrong in
either direction costs money: assume it failed and retry, you are double-sent;
assume it worked, you are short a position you think you have.

**`UNSENT` is not the same as `REJECTED`.** `UNSENT` means the order provably
never reached the broker — the governor refused it, the kill switch was
tripped, or a query afterwards found no trace of it. `REJECTED` means the
broker saw it and said no. They are both terminal and they mean opposite
things about whether the exchange has a record.

The one asymmetry in the table is deliberate: **only a query may leave
`UNKNOWN`.** `QUERY_FAILED` maps `UNKNOWN` back to `UNKNOWN`, so an order
whose broker cannot be reached stays unresolved for as long as that is true.
It is tempting to add a timeout that gives up and calls it dead. That would be
the assumption the rule forbids, so the machine simply cannot express it.
"""

from __future__ import annotations

from enum import StrEnum


class OrderState(StrEnum):
    INTENT = "intent"
    """Written to the journal, not yet handed to a broker. Durable before the
    network call, which is what makes a crash recoverable at all."""

    SENT = "sent"
    """Handed to the adapter, which returned without error. The broker has it
    or is about to; no acknowledgement yet."""

    ACKNOWLEDGED = "acknowledged"
    """The broker confirmed it and is working it."""

    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    """Terminal. The broker saw it and refused it."""

    UNSENT = "unsent"
    """Terminal. Provably never reached the broker: refused locally, or a
    query found no trace of it. Distinct from REJECTED because the exchange
    has no record of this order."""

    UNKNOWN = "unknown"
    """We do not know whether the broker has it. Only a query leaves here."""


TERMINAL: frozenset[OrderState] = frozenset(
    {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.UNSENT}
)
"""No event moves an order out of these. A terminal order is history."""


class Event(StrEnum):
    """Something that happened to an order. The only way state changes."""

    CREATED = "created"
    """The order was journalled. Never applied to an existing order — it is
    how one comes into being, which is why the table has no row for it."""

    SEND_OK = "send_ok"
    SEND_REFUSED = "send_refused"
    """The send was stopped before any bytes left — governor, kill switch, or
    local validation. Definite, which is why it resolves to UNSENT."""

    SEND_AMBIGUOUS = "send_ambiguous"
    """A timeout or connection error. We do not know. This is the event that
    UNKNOWN exists for."""

    PROCESS_RESTART = "process_restart"
    """Recovery found this order in flight in the journal. Whatever happened
    while the process was dead is not knowable from local state."""

    ACK = "ack"
    PARTIAL_FILL = "partial_fill"
    FILL = "fill"
    CANCEL = "cancel"
    REJECT = "reject"

    QUERY_FOUND_RESTING = "query_found_resting"
    QUERY_FOUND_PARTIAL = "query_found_partial"
    QUERY_FOUND_FILLED = "query_found_filled"
    QUERY_FOUND_CANCELLED = "query_found_cancelled"
    QUERY_FOUND_REJECTED = "query_found_rejected"
    QUERY_ABSENT = "query_absent"
    """The broker has no record of this client order id."""

    QUERY_FAILED = "query_failed"
    """The query itself failed. Resolves nothing, and deliberately so."""


QUERY_EVENTS: frozenset[Event] = frozenset(
    {
        Event.QUERY_FOUND_RESTING,
        Event.QUERY_FOUND_PARTIAL,
        Event.QUERY_FOUND_FILLED,
        Event.QUERY_FOUND_CANCELLED,
        Event.QUERY_FOUND_REJECTED,
        Event.QUERY_ABSENT,
        Event.QUERY_FAILED,
    }
)
"""The only events permitted to act on an UNKNOWN order. A test asserts that
every UNKNOWN transition in the table below uses one of these, so the rule
survives someone adding a row without reading this docstring."""


TRANSITIONS: dict[tuple[OrderState, Event], OrderState] = {
    (OrderState.INTENT, Event.SEND_OK): OrderState.SENT,
    (OrderState.INTENT, Event.SEND_REFUSED): OrderState.UNSENT,
    # The broker validated the order inside the `place` call and refused it —
    # margin, an untradable instrument, a bad price band. It never reached the
    # SENT state because the send is what rejected it. Distinct from
    # SEND_REFUSED, which is *us* stopping it before the broker ever saw it.
    (OrderState.INTENT, Event.REJECT): OrderState.REJECTED,
    (OrderState.INTENT, Event.SEND_AMBIGUOUS): OrderState.UNKNOWN,
    (OrderState.INTENT, Event.PROCESS_RESTART): OrderState.UNKNOWN,
    #
    (OrderState.SENT, Event.ACK): OrderState.ACKNOWLEDGED,
    (OrderState.SENT, Event.PARTIAL_FILL): OrderState.PARTIALLY_FILLED,
    (OrderState.SENT, Event.FILL): OrderState.FILLED,
    (OrderState.SENT, Event.CANCEL): OrderState.CANCELLED,
    (OrderState.SENT, Event.REJECT): OrderState.REJECTED,
    (OrderState.SENT, Event.SEND_AMBIGUOUS): OrderState.UNKNOWN,
    (OrderState.SENT, Event.PROCESS_RESTART): OrderState.UNKNOWN,
    #
    (OrderState.ACKNOWLEDGED, Event.PARTIAL_FILL): OrderState.PARTIALLY_FILLED,
    (OrderState.ACKNOWLEDGED, Event.FILL): OrderState.FILLED,
    (OrderState.ACKNOWLEDGED, Event.CANCEL): OrderState.CANCELLED,
    (OrderState.ACKNOWLEDGED, Event.REJECT): OrderState.REJECTED,
    (OrderState.ACKNOWLEDGED, Event.PROCESS_RESTART): OrderState.UNKNOWN,
    #
    (OrderState.PARTIALLY_FILLED, Event.PARTIAL_FILL): OrderState.PARTIALLY_FILLED,
    (OrderState.PARTIALLY_FILLED, Event.FILL): OrderState.FILLED,
    (OrderState.PARTIALLY_FILLED, Event.CANCEL): OrderState.CANCELLED,
    (OrderState.PARTIALLY_FILLED, Event.PROCESS_RESTART): OrderState.UNKNOWN,
    #
    (OrderState.UNKNOWN, Event.QUERY_FOUND_RESTING): OrderState.ACKNOWLEDGED,
    (OrderState.UNKNOWN, Event.QUERY_FOUND_PARTIAL): OrderState.PARTIALLY_FILLED,
    (OrderState.UNKNOWN, Event.QUERY_FOUND_FILLED): OrderState.FILLED,
    (OrderState.UNKNOWN, Event.QUERY_FOUND_CANCELLED): OrderState.CANCELLED,
    (OrderState.UNKNOWN, Event.QUERY_FOUND_REJECTED): OrderState.REJECTED,
    (OrderState.UNKNOWN, Event.QUERY_ABSENT): OrderState.UNSENT,
    (OrderState.UNKNOWN, Event.QUERY_FAILED): OrderState.UNKNOWN,
}


class IllegalTransition(ValueError):
    """An event that makes no sense for the state the order is in.

    Raised rather than ignored. A duplicate fill on an already-filled order is
    not a harmless no-op — it means the local view and the broker's view have
    diverged, and swallowing it is how a position break becomes invisible.
    """


def transition(state: OrderState, event: Event) -> OrderState:
    """Apply one event. The only way an order's state ever changes."""
    try:
        return TRANSITIONS[(state, event)]
    except KeyError:
        detail = (
            "it is terminal; terminal orders are history"
            if state in TERMINAL
            else "no such transition"
        )
        msg = f"cannot apply {event.value!r} to an order in {state.value!r}: {detail}"
        raise IllegalTransition(msg) from None


def is_terminal(state: OrderState) -> bool:
    return state in TERMINAL


def is_in_flight(state: OrderState) -> bool:
    """Live at, or possibly live at, the broker.

    `UNKNOWN` counts as in flight. It is the whole point: an order we cannot
    account for must be treated as potentially working, never as finished.
    """
    return state not in TERMINAL


def needs_resolution(state: OrderState) -> bool:
    return state is OrderState.UNKNOWN
