"""Angel One minute bars for sessions Kite missed (ADR-157)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

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
