"""Registry of derivative contracts, built from F&O bhavcopy.

`derivatives.py` gives a contract a stable key. This turns a stream of daily
rows into a registry that can answer questions about a contract's life: when it
first and last traded, what its lot size was on a given date, and which
contracts existed on some past day.

Lot size is the field that matters most here, and the reason it must be
time-versioned rather than looked up: index lot sizes are periodically reset to
hold notional in a band, so a contract's lot size is a fact about a *date*, not
about the contract. Hardcoding one silently misprices every position in the
periods where it was different.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date

from eulerlab.master.derivatives import ContractId
from eulerlab.master.registry import History


@dataclass
class Contract:
    """One derivative contract's observed life."""

    contract_id: ContractId
    lot_size: History[int] = field(default_factory=History)
    first_seen: date | None = None
    last_seen: date | None = None

    def observe(self, as_of: date, *, lot_size: int | None = None) -> None:
        if lot_size is not None:
            self.lot_size.observe(as_of, lot_size)
        if self.first_seen is None:
            self.first_seen = as_of
        self.last_seen = as_of

    def was_traded_on(self, as_of: date) -> bool:
        if self.first_seen is None or self.last_seen is None:
            return False
        return self.first_seen <= as_of <= self.last_seen

    @property
    def lot_size_changed(self) -> bool:
        return len(self.lot_size) > 1


class ContractRegistry:
    """Every derivative contract seen, keyed by its composite id."""

    def __init__(self) -> None:
        self._by_id: dict[ContractId, Contract] = {}

    def observe(
        self, as_of: date, contract_id: ContractId, *, lot_size: int | None = None
    ) -> Contract:
        contract = self._by_id.get(contract_id)
        if contract is None:
            contract = Contract(contract_id=contract_id)
            self._by_id[contract_id] = contract
        contract.observe(as_of, lot_size=lot_size)
        return contract

    def get(self, contract_id: ContractId) -> Contract | None:
        return self._by_id.get(contract_id)

    def lot_size_at(self, contract_id: ContractId, as_of: date) -> int | None:
        """The lot size in force on `as_of` — the Sprint 3 acceptance question."""
        contract = self._by_id.get(contract_id)
        return contract.lot_size.at(as_of) if contract else None

    def underlying_lot_size_at(self, underlying: str, as_of: date) -> int | None:
        """Lot size for an underlying on a date, from any contract on it.

        Contracts on one underlying share a lot size, so any live contract
        answers. Used to check a lot size without knowing a specific expiry.
        """
        for contract_id, contract in self._by_id.items():
            if contract_id.underlying != underlying:
                continue
            if not contract.was_traded_on(as_of):
                continue
            size = contract.lot_size.at(as_of)
            if size is not None:
                return size
        return None

    def live_on(self, as_of: date) -> Iterator[Contract]:
        return (c for c in self._by_id.values() if c.was_traded_on(as_of))

    def underlyings(self) -> set[str]:
        return {cid.underlying for cid in self._by_id}

    def __len__(self) -> int:
        return len(self._by_id)
