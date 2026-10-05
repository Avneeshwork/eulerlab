"""The option-chain recorder.

The failure this guards against is the one it already made: `/option-chain-v3`
requires an `expiry` parameter and, without one, returns an empty row set
rather than an error. An empty success reads as "the market has no options
today", so the first version reported four symbols unavailable while NSE was
serving all four perfectly well. Nothing in the response said anything was
wrong.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.ingest import nse_chain


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class FakeSession:
    """Records what was asked for, so the expiry parameter can be asserted."""

    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads: dict[str, Any] = payloads
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str] | None = None, timeout: object = None):  # type: ignore[no-untyped-def]
        self.calls.append((url, params or {}))
        key = "contract" if "contract-info" in url else "chain"
        return FakeResponse(self.payloads[key])

    def close(self) -> None:
        return None


CHAIN: dict[str, Any] = {
    "records": {
        "underlyingValue": 22555.75,
        "expiryDates": ["06-Oct-2026", "13-Oct-2026"],
        "data": [
            {
                "strikePrice": 22500,
                "CE": {
                    "expiryDate": "06-Oct-2026",
                    "lastPrice": 120.0,
                    "buyPrice1": 119.5,
                    "sellPrice1": 120.5,
                    "buyQuantity1": 100,
                    "sellQuantity1": 200,
                    "impliedVolatility": 12.5,
                    "openInterest": 5000,
                    "changeinOpenInterest": -100,
                    "totalTradedVolume": 9000,
                    "totalBuyQuantity": 1,
                    "totalSellQuantity": 2,
                },
                "PE": {
                    "expiryDate": "06-Oct-2026",
                    "lastPrice": 110.0,
                    "buyPrice1": 109.0,
                    "sellPrice1": 111.0,
                    "buyQuantity1": 10,
                    "sellQuantity1": 20,
                    "impliedVolatility": 12.1,
                    "openInterest": 4000,
                    "changeinOpenInterest": 50,
                    "totalTradedVolume": 7000,
                    "totalBuyQuantity": 3,
                    "totalSellQuantity": 4,
                },
            }
        ],
    }
}

CONTRACT: dict[str, Any] = {"expiryDates": ["06-Oct-2026", "13-Oct-2026"]}


def test_the_chain_request_carries_an_expiry() -> None:
    """Without it NSE answers 200 with no rows, which is not an error."""
    session = FakeSession({"contract": CONTRACT, "chain": CHAIN})
    nse_chain.fetch("NIFTY", "06-Oct-2026", session=session)

    url, params = session.calls[-1]
    assert "option-chain-v3" in url
    assert params["expiry"] == "06-Oct-2026", "the parameter whose absence caused the bug"
    assert params["symbol"] == "NIFTY"


def test_an_empty_row_set_raises_rather_than_landing_nothing() -> None:
    """An empty chain and a refused chain are different facts."""
    session = FakeSession({"contract": CONTRACT, "chain": {"records": {"data": []}}})
    with pytest.raises(nse_chain.ChainUnavailable):
        nse_chain.fetch("NIFTY", "06-Oct-2026", session=session)


def test_every_record_is_bitemporally_stamped() -> None:
    """CLAUDE.md: event_time and knowledge_time on every stored record, no
    exceptions. For a live snapshot they are the same instant, which is the
    point of recording it rather than reconstructing it later."""
    session = FakeSession({"contract": CONTRACT, "chain": CHAIN})
    snapshot = nse_chain.fetch("NIFTY", "06-Oct-2026", session=session)
    records = nse_chain._records(snapshot)

    assert len(records) == 2, "one row per right"
    for record in records:
        assert record["event_time"] and record["knowledge_time"]
        assert record["event_time"] == record["knowledge_time"]


def test_it_keeps_the_columns_the_bhavcopy_has_no_room_for() -> None:
    """Bid, ask and implied volatility are the whole reason this exists."""
    session = FakeSession({"contract": CONTRACT, "chain": CHAIN})
    records = nse_chain._records(nse_chain.fetch("NIFTY", "06-Oct-2026", session=session))
    call = next(r for r in records if r["right"] == "CE")

    assert call["bid"] == 119.5
    assert call["ask"] == 120.5
    assert call["implied_volatility"] == 12.5
    assert call["change_in_open_interest"] == -100


def test_a_snapshot_lands_as_one_immutable_file(tmp_path: Path) -> None:
    """One file per snapshot. Appending to a daily file would let a re-run
    corrupt what an earlier one wrote, and landed data is beyond editing."""
    session = FakeSession({"contract": CONTRACT, "chain": CHAIN})
    snapshot = nse_chain.fetch("NIFTY", "06-Oct-2026", session=session)
    snapshot.taken_at = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)

    written = nse_chain.land(snapshot, directory=tmp_path)
    assert written.exists()
    assert "06-Oct-2026" in written.name, "the expiry must be in the name, not just the time"

    with gzip.open(written, "rt") as handle:
        rows = [json.loads(line) for line in handle]
    assert len(rows) == 2
    assert {r["right"] for r in rows} == {"CE", "PE"}


def test_expiries_come_from_the_contract_endpoint() -> None:
    session = FakeSession({"contract": CONTRACT, "chain": CHAIN})
    assert nse_chain.expiries("NIFTY", session=session) == ["06-Oct-2026", "13-Oct-2026"]
    assert "contract-info" in session.calls[-1][0]
