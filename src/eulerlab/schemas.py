"""Canonical data contracts.

**STUB — Sprint 0.** This is not the order schema. The real one is designed in
Sprint 19 alongside the OMS state machine, and will carry timestamps, state,
venue, fills, and the reproducibility triple (``git_sha``, ``config_hash``,
``signal_id``).

What exists here is the minimum needed to reserve the ``algo_id`` field, which
the exchange assigns and which must be echoed on every placement, modification
and cancellation in India. Adding that field to a schema today costs five
minutes. Adding it once the OMS, reconciler, event log and attribution system
all read the schema costs a week of migrations.

Do not build on this model. Do not import it into anything that runs.
See ``docs/STUBS.md`` (S-001).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Order(BaseModel):
    """Placeholder order. See module docstring before using."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_order_id: str = Field(min_length=1)
    """Deterministic: hash(strategy_id, signal_time, instrument_id, seq).

    Deterministic IDs are what make a retry after a timeout safe. Sprint 19
    implements the derivation; this field only reserves the name.
    """

    instrument_id: int = Field(gt=0)
    """Internal security-master ID. Never a ticker, tradingsymbol or broker token."""

    side: Literal["BUY", "SELL"]

    quantity: int = Field(gt=0)

    algo_id: str | None = None
    """Exchange-assigned algo identifier (India). Nullable and unused in Sprint 0."""
