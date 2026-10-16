from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from eulerlab.ingest import kite_mcx_gold as ingest
from eulerlab.ingest.kite_minute import Chunk, MinuteStore
from eulerlab.intraday.mcx_gold_backtest import Bar, run_backtest

MASTER = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
    "tick_size,lot_size,instrument_type,segment,exchange\n"
    "101,1,GOLD26DECFUT,GOLD,0,2026-12-04,,1,1,FUT,MCX,MCX\n"
    "102,2,GOLDM26NOVFUT,GOLDM,0,2026-11-05,,1,1,FUT,MCX,MCX\n"
    "103,3,GOLD26OCT65000CE,GOLD,0,2026-10-30,65000,1,1,CE,MCX-OPT,MCX\n"
)


def test_front_contract_selects_standard_gold_and_not_mini_or_options(tmp_path: Path) -> None:
    master = tmp_path / "instruments.csv"
    master.write_text(MASTER)
    selected = ingest._front_gold_contract(master, date(2026, 10, 15))
    assert selected["tradingsymbol"] == "GOLD26DECFUT"
    assert selected["instrument_token"] == "101"


def test_historical_client_uses_chunk_market_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.ingest.kite_minute import KiteHistorical

    client = KiteHistorical("key", "token")
    requested: list[str] = []

    def fake_get(url: str, timeout: float = 60.0) -> bytes:
        requested.append(url)
        return b'{"data":{"candles":[]}}'

    monkeypatch.setattr(client, "_get", fake_get)
    client.candles(
        Chunk(
            "GOLD26DECFUT",
            101,
            date(2026, 10, 14),
            date(2026, 10, 14),
            from_time="09:00:00",
            to_time="23:55:00",
        )
    )
    assert "from=2026-10-14+09%3A00%3A00" in requested[0]
    assert "to=2026-10-14+23%3A55%3A00" in requested[0]


def test_fetch_lands_evening_session_and_stops_before_first_empty_month(tmp_path: Path) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[Chunk] = []

        def candles(self, chunk: Chunk, interval: str = "minute") -> list[list[object]]:
            assert interval == "minute"
            assert chunk.from_time == "09:00:00"
            assert chunk.to_time == "23:55:00"
            self.calls.append(chunk)
            if chunk.start.year == 2026 and chunk.start.month >= 9:
                return [[f"{chunk.start}T22:00:00+0530", 1, 2, 0.5, 1.5, 10]]
            return []

    client = FakeClient()
    store = MinuteStore(tmp_path)
    result = ingest.fetch_available_history(
        client,
        store,
        {"tradingsymbol": "GOLD26DECFUT", "instrument_token": "101"},
        end=date(2026, 10, 14),
        years=5,
        sleep_s=0,
    )
    manifest = [json.loads(line) for line in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert result["rows"] == len(manifest)
    assert all(row["symbol"] == "GOLD26DECFUT" for row in manifest)
    assert any(
        call.start == date(2026, 9, 1) and call.end == date(2026, 9, 30) for call in client.calls
    )
    assert client.calls[-1].start == date(2026, 8, 1)


def test_mcx_gold_rule_runs_fixed_parameters_and_charges_futures_costs() -> None:
    bars = [
        Bar(100_000 + i * 100, 100_100 + i * 100, 99_900 + i * 100, 100_100 + i * 100, 1)
        for i in range(180)
    ]
    result = run_backtest({date(2026, 10, 1): bars}, symbol="GOLD26DECFUT", lot_size=1)
    assert result["settings"]["period_5m_bars"] == 50
    assert result["settings"]["dead_band_bps"] == 20
    assert result["fills"] > 0
    assert result["costs"]["fees_rupees"] > 0
    assert result["long_intraday_benchmark"]["net"]["sessions"] == 1
