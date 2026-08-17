"""Guards on the Order placeholder.

These tests exist to prove the ``algo_id`` field survives to Sprint 19. If
someone deletes it, this goes red and the review has to explain why.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from eulerlab.schemas import Order


def _order(**overrides: object) -> Order:
    fields: dict[str, object] = {
        "client_order_id": "abc123",
        "instrument_id": 1,
        "side": "BUY",
        "quantity": 10,
    }
    fields.update(overrides)
    return Order.model_validate(fields)


def test_algo_id_exists_and_defaults_to_none() -> None:
    assert _order().algo_id is None


def test_algo_id_round_trips() -> None:
    assert _order(algo_id="NSE-ALGO-1").algo_id == "NSE-ALGO-1"


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _order(quantity=0)


def test_side_is_constrained() -> None:
    with pytest.raises(ValidationError):
        _order(side="LONG")


def test_orders_are_immutable() -> None:
    with pytest.raises(ValidationError):
        _order().quantity = 5  # type: ignore[misc]


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _order(tradingsymbol="NIFTY24AUG")
