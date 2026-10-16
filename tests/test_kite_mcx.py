"""The MCX snapshot keeps only valid MCX rows and lands source bytes unchanged."""

from __future__ import annotations

import gzip
from datetime import date
from pathlib import Path

import pytest

from eulerlab.ingest.fetch import FetchResult, Outcome
from eulerlab.ingest.kite_mcx import KiteMCXError, fetch_snapshot, parse_mcx_instruments
from eulerlab.ingest.landing import Landing

HEADER = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
    "tick_size,lot_size,instrument_type,segment,exchange\n"
)
MCX = (
    "12345,12345,GOLDM26OCTFUT,GOLDM,0,2026-10-30,,1,10,FUT,MCX,MCX\n"
    "12346,12346,GOLDM26OCT65000CE,GOLDM,0,2026-10-30,65000,1,10,CE,MCX,MCX\n"
)
CSV = (HEADER + MCX).encode()


def test_parse_keeps_mcx_contract_fields_and_ignores_other_exchanges() -> None:
    payload = CSV + b"555,555,INFY,INFOSYS,0,,,,1,EQ,NSE,NSE\n"

    rows = parse_mcx_instruments(payload)

    assert [row["tradingsymbol"] for row in rows] == ["GOLDM26OCTFUT", "GOLDM26OCT65000CE"]
    assert rows[0]["expiry"] == "2026-10-30"
    assert rows[0]["lot_size"] == "10"
    assert rows[1]["strike"] == "65000"


def test_parser_accepts_the_gzipped_csv_response() -> None:
    assert len(parse_mcx_instruments(gzip.compress(CSV))) == 2


@pytest.mark.parametrize("payload", [b"<html>denied</html>", HEADER.encode()])
def test_invalid_or_empty_response_is_rejected(payload: bytes) -> None:
    with pytest.raises(KiteMCXError):
        parse_mcx_instruments(payload)


class FakeFetcher:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls = 0

    def get(self, url: str) -> FetchResult:
        self.calls += 1
        return FetchResult(Outcome.OK, url, payload=self.payload, status=200)


def test_fetch_lands_exact_source_bytes_and_is_idempotent(tmp_path: Path) -> None:
    fetcher = FakeFetcher(CSV)
    landing = Landing(tmp_path)
    day = date(2026, 10, 15)

    assert fetch_snapshot(fetcher, landing, day) == "downloaded"
    entry = landing.entries()[(day.isoformat(), "instruments")]
    assert (tmp_path / entry.path).read_bytes() == CSV
    assert entry.rows == 2
    assert fetch_snapshot(fetcher, landing, day) == "skipped"
    assert fetcher.calls == 1


def test_malformed_response_does_not_land(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    with pytest.raises(KiteMCXError):
        fetch_snapshot(FakeFetcher(b"<html>denied</html>"), landing, date(2026, 10, 15))
    assert not landing.entries()
