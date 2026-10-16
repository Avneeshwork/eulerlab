from __future__ import annotations

from datetime import date
from pathlib import Path

from eulerlab.ingest.angel_mcx_gold import (
    _expiry,
    _windows,
    fetch_history,
    resolve_front_contract,
)
from eulerlab.ingest.kite_minute import MinuteStore


class FakeAngel:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def searchScrip(self, exchange: str, searchscrip: str) -> dict[str, object]:
        assert (exchange, searchscrip) == ("MCX", "GOLD")
        return {
            "status": True,
            "data": [
                {"exchange": "MCX", "tradingsymbol": "GOLD04DEC26FUT", "symboltoken": "495213"},
                {"exchange": "MCX", "tradingsymbol": "GOLD05FEB27FUT", "symboltoken": "559933"},
                {"exchange": "MCX", "tradingsymbol": "GOLD04DEC26CE", "symboltoken": "1"},
            ],
        }

    def getCandleData(self, params: dict[str, str]) -> dict[str, object]:
        self.calls.append(params)
        return {
            "status": True,
            "data": [["2026-10-13T17:00:00+05:30", 149000, 149100, 148900, 149050, 120]],
        }


def test_expiry_accepts_contract_format_and_rejects_options() -> None:
    assert _expiry("GOLD04DEC26FUT") == date(2026, 12, 4)
    assert _expiry("GOLD04DEC26CE") is None
    assert _expiry("GOLDM04DEC26FUT") is None


def test_resolve_front_contract_selects_nearest_unexpired_standard_gold() -> None:
    client = FakeAngel()
    assert resolve_front_contract(client, date(2026, 10, 15)) == {
        "symbol": "GOLD04DEC26FUT",
        "token": "495213",
        "expiry": "2026-12-04",
    }


def test_windows_are_fixed_and_cover_range_without_overlap() -> None:
    assert _windows(date(2026, 10, 13), date(2026, 10, 16)) == [
        (date(2026, 10, 13), date(2026, 10, 13)),
        (date(2026, 10, 14), date(2026, 10, 14)),
        (date(2026, 10, 15), date(2026, 10, 15)),
        (date(2026, 10, 16), date(2026, 10, 16)),
    ]


def test_fetch_history_lands_data_and_skips_existing_window(tmp_path: Path) -> None:
    client = FakeAngel()
    store = MinuteStore(tmp_path)
    contract = {"symbol": "GOLD04DEC26FUT", "token": "495213", "expiry": "2026-12-04"}

    first = fetch_history(
        client,
        store,
        contract,
        start=date(2026, 10, 13),
        end=date(2026, 10, 13),
        delay_s=0,
    )
    assert first["rows"] == 1
    assert len(client.calls) == 1
    assert client.calls[0]["exchange"] == "MCX"
    assert client.calls[0]["interval"] == "ONE_MINUTE"
    assert client.calls[0]["symboltoken"] == "495213"

    second = fetch_history(
        client,
        store,
        contract,
        start=date(2026, 10, 13),
        end=date(2026, 10, 13),
        delay_s=0,
    )
    assert second["skipped"] == 1
    assert len(client.calls) == 1
