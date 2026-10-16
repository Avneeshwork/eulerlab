from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from eulerlab.ingest import kite_mcx_indices as ingest
from eulerlab.ingest.kite_minute import Chunk, MinuteStore, parse_instruments


def test_specs_cover_the_image_and_keep_unavailable_indices_explicit() -> None:
    assert len(ingest.INDEX_SPECS) == 12
    names = {spec.name for spec in ingest.INDEX_SPECS}
    assert "MCX iCOMDEX Aluminium" in names
    assert "MCX iCOMDEX Natural Gas" in names
    assert not any("Nickel" in name for name in names)
    energy = next(spec for spec in ingest.INDEX_SPECS if spec.name.endswith("Energy"))
    assert energy.symbol == "MCXENERGY"
    assert "returned no candles" in energy.reason


def test_mcx_index_tokens_can_be_resolved_from_the_shared_kite_parser() -> None:
    payload = (
        b"instrument_token,tradingsymbol,instrument_type,exchange\n"
        b"273417,MCXGOLDEX,EQ,MCX\n"
        b"256265,RELIANCE,EQ,NSE\n"
        b"123456,MCXGOLDEX,FUT,MCX\n"
    )
    assert parse_instruments(payload, exchange="MCX") == {"MCXGOLDEX": 273417}


def test_backfill_lands_supported_chunks_and_records_missing_symbols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ingest,
        "INDEX_SPECS",
        (
            ingest.IndexSpec("MCX iCOMDEX Test", "TESTDEX"),
            ingest.IndexSpec("MCX iCOMDEX Missing", None, "not listed"),
        ),
    )

    class FakeClient:
        def instruments(self, exchange: str = "NSE") -> dict[str, int]:
            assert exchange == "MCX"
            return {"TESTDEX": 123}

        def candles(self, chunk: Chunk, interval: str = "minute") -> list[list[object]]:
            assert interval == "minute"
            assert chunk.token == 123
            return [["2026-10-14T09:15:00+0530", 1, 2, 0.5, 1.5, 10]]

    result = ingest.backfill(
        FakeClient(), MinuteStore(tmp_path), end=date(2026, 10, 14), years=1, sleep_s=0
    )

    assert result == {"downloaded": 7, "skipped": 0, "rows": 7, "failed": 0}
    manifest = [json.loads(line) for line in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert manifest[0]["symbol"] == "TESTDEX"
    assert manifest[0]["rows"] == 1
    unresolved = [
        json.loads(line) for line in (tmp_path / "unresolved.jsonl").read_text().splitlines()
    ]
    assert unresolved == [
        {"reason": "not listed", "resolved": False, "symbol": "MCX iCOMDEX Missing"}
    ]
