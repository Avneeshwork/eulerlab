"""The state machine, tested for the properties that keep money safe.

Most of these are checks on the *table* rather than on a scenario. A table is
data, and data is what someone adds a row to six months from now without
reading the docstring above it — so the rules that matter are asserted against
every row, not against the rows I happened to think of.
"""

from __future__ import annotations

import pytest

from eulerlab.oms.states import (
    QUERY_EVENTS,
    TERMINAL,
    TRANSITIONS,
    Event,
    IllegalTransition,
    OrderState,
    is_in_flight,
    is_terminal,
    needs_resolution,
    transition,
)


def test_only_a_query_can_leave_unknown() -> None:
    """CLAUDE.md: an UNKNOWN order is resolved by querying, never by assuming.

    Asserted over the whole table so a future row cannot quietly add an
    assumption — which would look like a small convenience and would be the
    single most expensive line in the system.
    """
    for (state, event), _ in TRANSITIONS.items():
        if state is OrderState.UNKNOWN:
            assert event in QUERY_EVENTS, f"{event} escapes UNKNOWN without asking the broker"


def test_a_failed_query_resolves_nothing() -> None:
    assert transition(OrderState.UNKNOWN, Event.QUERY_FAILED) is OrderState.UNKNOWN


def test_there_is_no_timeout_that_gives_up_on_an_unknown_order() -> None:
    """The tempting feature: after N failed queries, call it dead. There is no
    event for it, so the machine cannot express it at all."""
    escapes = {e for (s, e) in TRANSITIONS if s is OrderState.UNKNOWN}
    assert Event.PROCESS_RESTART not in escapes
    assert Event.SEND_REFUSED not in escapes


def test_terminal_states_accept_nothing() -> None:
    for state in TERMINAL:
        for event in Event:
            with pytest.raises(IllegalTransition):
                transition(state, event)


def test_a_duplicate_fill_raises_rather_than_being_ignored() -> None:
    """A second fill on a filled order means our view and the broker's have
    diverged. Swallowing it is how a position break becomes invisible."""
    with pytest.raises(IllegalTransition, match="terminal"):
        transition(OrderState.FILLED, Event.FILL)


def test_unsent_and_rejected_are_different_things() -> None:
    """Both terminal, opposite meanings: one the exchange never saw, the other
    it saw and refused."""
    assert transition(OrderState.INTENT, Event.SEND_REFUSED) is OrderState.UNSENT
    assert transition(OrderState.SENT, Event.REJECT) is OrderState.REJECTED
    assert len({OrderState.UNSENT, OrderState.REJECTED}) == 2


def test_an_ambiguous_send_is_unknown_from_either_state() -> None:
    assert transition(OrderState.INTENT, Event.SEND_AMBIGUOUS) is OrderState.UNKNOWN
    assert transition(OrderState.SENT, Event.SEND_AMBIGUOUS) is OrderState.UNKNOWN


def test_a_restart_makes_every_live_order_unknown() -> None:
    """Including ACKNOWLEDGED. What we knew before the process died is a cache,
    and a cache that outlived its process is stale by definition."""
    for state in (
        OrderState.INTENT,
        OrderState.SENT,
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIALLY_FILLED,
    ):
        assert transition(state, Event.PROCESS_RESTART) is OrderState.UNKNOWN


def test_unknown_counts_as_in_flight() -> None:
    """An order we cannot account for must be treated as possibly working."""
    assert is_in_flight(OrderState.UNKNOWN)
    assert not is_terminal(OrderState.UNKNOWN)
    assert needs_resolution(OrderState.UNKNOWN)


def test_every_state_is_reachable() -> None:
    """A state nothing can reach is dead code pretending to be a safeguard."""
    reachable = {OrderState.INTENT} | set(TRANSITIONS.values())
    assert reachable == set(OrderState)


def test_created_has_no_row_in_the_table() -> None:
    """CREATED is how an order comes into being, not something applied to one."""
    assert not any(event is Event.CREATED for (_, event) in TRANSITIONS)


def test_partial_fills_can_repeat() -> None:
    state = transition(OrderState.ACKNOWLEDGED, Event.PARTIAL_FILL)
    assert transition(state, Event.PARTIAL_FILL) is OrderState.PARTIALLY_FILLED
    assert transition(state, Event.FILL) is OrderState.FILLED


def test_a_broker_can_reject_at_the_moment_of_sending() -> None:
    """Some brokers validate inside the place call: margin, price bands, an
    untradable instrument. The order never reaches SENT because the send is
    what refused it — and it is REJECTED, not UNSENT, because the broker saw it."""
    assert transition(OrderState.INTENT, Event.REJECT) is OrderState.REJECTED
    assert transition(OrderState.INTENT, Event.SEND_REFUSED) is OrderState.UNSENT
