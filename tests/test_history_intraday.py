"""The chart's intraday candles: rolled up from minute bars, timed in IST."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from eulerlab.api import server
from eulerlab.intraday import store
from eulerlab.intraday.tweezer import IST, Candle


def _minutes(day: int, count: int) -> list[Candle]:
    out = []
    for m in range(count):
        hour, minute = divmod(9 * 60 + 15 + m, 60)
        price = 100.0 + m
        out.append(
            Candle(
                ts=datetime(2026, 10, day, hour, minute, tzinfo=IST),
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price + 0.25,
                volume=10.0,
            )
        )
    return out


@pytest.fixture
def minutes(monkeypatch: pytest.MonkeyPatch) -> list[date | None]:
    asked: list[date | None] = []

    def fake_fetch(
        symbol: str, *, start: date | None = None, end: date | None = None
    ) -> list[Candle]:
        asked.append(start)
        return _minutes(29, 10) + _minutes(30, 10) if symbol == "NIFTYBEES" else []

    monkeypatch.setattr(store, "fetch", fake_fetch)
    return asked


def test_five_minute_candles_per_session(minutes: list[date | None]) -> None:
    found = server.history_intraday("niftybees", minutes=5, days=10)
    assert found["ok"] is True
    bars = found["bars"]
    assert len(bars) == 4  # two five-minute buckets in each of two sessions
    first = bars[0]
    assert (first["open"], first["close"]) == (100.0, 104.25)
    assert (first["high"], first["low"]) == (104.5, 99.5)
    assert first["volume"] == 50.0
    # The axis key reads as IST wall-clock time: 09:15 on 29 Oct.
    assert (
        datetime.fromtimestamp(first["time"], UTC).strftime("%Y-%m-%d %H:%M") == "2026-10-29 09:15"
    )
    assert found["last"] == "2026-10-30 09:20"


def test_refuses_an_unknown_candle_size(minutes: list[date | None]) -> None:
    found = server.history_intraday("NIFTYBEES", minutes=7)
    assert found["ok"] is False
    assert minutes == []


def test_names_a_symbol_with_no_minutes(minutes: list[date | None]) -> None:
    found = server.history_intraday("TITAN", minutes=5, days=5000)
    assert found["ok"] is False
    assert "no minute bars for TITAN in the last 400 days" in found["error"]
