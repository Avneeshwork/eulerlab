"""Angel One minute bars for sessions Kite missed (ADR-157)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.ingest import angel_minute
from eulerlab.ingest.angel_minute import fetch_day, nse_tokens
from eulerlab.ingest.kite_minute import MinuteStore

MUHURAT = date(2026, 11, 8)


def test_tokens_cover_equities_and_the_three_indices() -> None:
    rows = [
        {"exch_seg": "NSE", "symbol": "ACME-BE", "token": "1"},
        {"exch_seg": "NSE", "symbol": "ACME-EQ", "token": "2"},
        {"exch_seg": "NSE", "symbol": "Nifty 50", "token": "99926000", "instrumenttype": "AMXIDX"},
        {"exch_seg": "NSE", "symbol": "India VIX", "token": "99926017", "instrumenttype": "AMXIDX"},
        {"exch_seg": "BSE", "symbol": "OTHER-EQ", "token": "3"},
    ]
    assert nse_tokens(rows) == {"ACME": "2", "NIFTY 50": "99926000", "INDIA VIX": "99926017"}


class _Client:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.calls = 0

    def getCandleData(self, params: dict[str, str]) -> Any:
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_a_day_lands_once_and_a_rate_limit_is_retried(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr("eulerlab.ingest.angel_minute.time.sleep", lambda _s: None)
    bars = [["2026-11-08T14:20:00+05:30", 1.0, 2.0, 0.5, 1.5, 10]]
    client = _Client([RuntimeError("exceeding access rate"), {"status": True, "data": bars}])
    store = MinuteStore(tmp_path)
    assert fetch_day(client, store, "ACME", "2", MUHURAT) == 1
    assert fetch_day(client, store, "ACME", "2", MUHURAT) == -1  # held: no second request
    assert client.calls == 2


def test_angel_bars_are_stored_as_kite_stores_them(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr("eulerlab.ingest.angel_minute.time.sleep", lambda _s: None)
    import json

    import pyarrow.parquet as pq

    bars = [["2026-11-09T15:29:00+05:30", 1.0, 2.0, 0.5, 1.5, 10]]
    store = MinuteStore(tmp_path)
    got = fetch_day(
        _Client([{"status": True, "data": bars}]), store, "ACME", "2", date(2026, 11, 9)
    )
    assert got == 1
    [row] = [json.loads(x) for x in store.manifest_path.read_text().splitlines()]
    assert row["source"] == "angel_one" and row["key"] == "ACME/2026-11-09"
    table = pq.read_table(tmp_path / row["path"])
    assert table.column("ts").to_pylist() == ["2026-11-09T15:29:00+0530"]  # Kite's format


def test_a_day_kite_already_holds_is_not_fetched(tmp_path: Path) -> None:
    from eulerlab.ingest.kite_minute import Chunk, candles_to_table

    store = MinuteStore(tmp_path)
    store.write(Chunk("ACME", 7, date(2026, 11, 2), date(2026, 11, 9)), candles_to_table([]))
    angel_minute._SPANS.clear()
    assert fetch_day(_Client([]), store, "ACME", "2", date(2026, 11, 6)) == -1


def test_an_unfinished_session_is_not_landed(tmp_path: Path) -> None:
    bars = [["2026-11-09T11:00:00+05:30", 1.0, 2.0, 0.5, 1.5, 10]]
    store = MinuteStore(tmp_path)
    client = _Client([{"status": True, "data": bars}])
    day = date(2026, 11, 9)
    assert fetch_day(client, store, "ACME", "2", day, today=day) == -2
    assert not store.manifest_path.exists()


def test_the_first_fills_are_copied_into_the_uniform_stores_once(tmp_path: Path) -> None:
    from eulerlab.ingest.kite_minute import Chunk, candles_to_table

    old = MinuteStore(tmp_path / "angel")
    bars = [["2026-11-08T18:00:00+05:30", 1.0, 2.0, 0.5, 1.5, 10]]
    old.write(Chunk("NIFTY 50", 99926000, MUHURAT, MUHURAT), candles_to_table(bars))
    old.write(Chunk("ACME", 2, MUHURAT, MUHURAT), candles_to_table(bars))
    angel_minute._SPANS.clear()
    args = (tmp_path / "angel", tmp_path / "kite", tmp_path / "index")
    assert angel_minute.migrate(*args) == 2
    assert angel_minute.migrate(*args) == 0
    assert (tmp_path / "index" / "NIFTY50" / "2026-11-08_2026-11-08.parquet").exists()
    assert (tmp_path / "kite" / "ACME" / "2026-11-08_2026-11-08.parquet").exists()
    assert (tmp_path / "angel" / "ACME" / "2026-11-08_2026-11-08.parquet").exists()  # kept
