"""Crypto day files beside month files, and the filler's window (T-4369).

The daily filler lands a month's days while the month is open; Binance's month
file for the same days lands later, and the day files stay. Readers read the
month file only. The filler starts at the first of the previous month, so the
last days of a month are filled before its month file is published.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab.features import alt_panel
from eulerlab.ingest import crypto, landing_reader
from eulerlab.intraday import crypto_store


def _write(path: Path, start: datetime, minutes: int, close: float = 100.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for index in range(minutes):
            when = start + timedelta(minutes=index)
            handle.write(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "open": close,
                        "high": close + 1,
                        "low": close - 1,
                        "close": close,
                        "volume": 2.0,
                        "trades": 1,
                        "event_time": when.isoformat(),
                        "knowledge_time": (when + timedelta(minutes=1)).isoformat(),
                    }
                )
                + "\n"
            )


def _month_and_day(root: Path) -> None:
    """Two days of August as a month file, and 1 August again as a day file."""
    folder = root / "BTCUSDT"
    _write(folder / "BTCUSDT-1m-2026-08.jsonl.gz", datetime(2026, 8, 1, tzinfo=UTC), 2880)
    _write(folder / "BTCUSDT-1m-2026-08-01.jsonl.gz", datetime(2026, 8, 1, tzinfo=UTC), 1440)


def test_a_day_file_its_month_file_covers_is_dropped() -> None:
    names = [
        "crypto/BTCUSDT/BTCUSDT-1m-2026-08-01.jsonl.gz",
        "crypto/BTCUSDT/BTCUSDT-1m-2026-08.jsonl.gz",
        "crypto/BTCUSDT/BTCUSDT-1m-2026-09-01.jsonl.gz",
        "crypto/ETHUSDT/ETHUSDT-1m-2026-09-02.jsonl.gz",
    ]
    assert crypto.without_superseded(names) == names[1:]


def test_one_symbols_month_does_not_hide_another_symbols_day() -> None:
    names = [
        "crypto/BTCUSDT/BTCUSDT-1m-2026-08.jsonl.gz",
        "crypto/ETHUSDT/ETHUSDT-1m-2026-08-01.jsonl.gz",
    ]
    assert crypto.without_superseded(names) == names


def test_daily_volume_is_counted_once_when_both_files_landed(tmp_path: Path) -> None:
    _month_and_day(tmp_path)
    rows = alt_panel.crypto_daily(directory=tmp_path)
    assert [r.day for r in rows] == [date(2026, 8, 1), date(2026, 8, 2)]
    # 1,440 minutes of volume 2: once, not twice.
    assert rows[0].volume == pytest.approx(2880.0)
    assert rows[0].turnover == pytest.approx(2880.0 * 100.0)


def test_the_cloud_path_counts_once_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _month_and_day(tmp_path / "crypto")
    monkeypatch.setattr(landing_reader, "LANDING_ROOT", tmp_path)
    monkeypatch.setattr(landing_reader, "cloud_enabled", lambda: False)
    rows = alt_panel.crypto_daily(symbols=["BTCUSDT"], start=date(2026, 8, 1))
    assert rows[0].volume == pytest.approx(2880.0)
    # Built once and kept: the month file only, saved for the next process.
    assert set(alt_panel._ROLLUPS) == {"crypto/BTCUSDT/BTCUSDT-1m-2026-08.jsonl.gz"}
    assert alt_panel.ROLLUP_CACHE.exists()


def test_a_saved_rollup_is_read_without_the_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The next process reads the saved bars; the minutes are not fetched."""
    _month_and_day(tmp_path / "crypto")
    monkeypatch.setattr(landing_reader, "LANDING_ROOT", tmp_path)
    monkeypatch.setattr(landing_reader, "cloud_enabled", lambda: False)
    first = alt_panel.crypto_daily(symbols=["BTCUSDT"], start=date(2026, 8, 1))

    monkeypatch.setattr(alt_panel, "_ROLLUPS", {})
    monkeypatch.setattr(alt_panel, "_ROLLUPS_LOADED", [])

    def no_download(relative: str, **_: object) -> bytes:
        raise AssertionError(f"downloaded {relative}")

    monkeypatch.setattr(landing_reader, "read", no_download)
    again = alt_panel.crypto_daily(symbols=["BTCUSDT"], start=date(2026, 8, 2))
    assert [r.day for r in again] == [date(2026, 8, 2)]
    assert again[0].volume == first[1].volume


def test_the_cloud_path_keeps_no_minutes_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pruned files are read with `cache=False`, so the landing tree is not refilled."""
    _month_and_day(tmp_path / "crypto")
    monkeypatch.setattr(landing_reader, "LANDING_ROOT", tmp_path)
    monkeypatch.setattr(landing_reader, "cloud_enabled", lambda: False)
    seen: list[bool] = []
    real = landing_reader.read

    def spy(relative: str, *, allow_cloud: bool = True, cache: bool = True) -> bytes:
        seen.append(cache)
        return real(relative, allow_cloud=allow_cloud, cache=cache)

    monkeypatch.setattr(landing_reader, "read", spy)
    alt_panel.crypto_daily(symbols=["BTCUSDT"], start=date(2026, 8, 1))
    assert seen == [False]


def test_minute_reader_gives_one_candle_a_minute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _month_and_day(tmp_path / "crypto")
    monkeypatch.setattr(landing_reader, "LANDING_ROOT", tmp_path)
    monkeypatch.setattr(landing_reader, "cloud_enabled", lambda: False)
    candles = crypto_store.fetch("BTCUSDT", start=date(2026, 8, 1), end=date(2026, 8, 1))
    assert len(candles) == 1440
    assert len({c.ts for c in candles}) == 1440


def test_the_window_starts_at_the_first_of_the_previous_month() -> None:
    assert crypto.fill_window(date(2026, 11, 1)) == date(2026, 10, 1)
    assert crypto.fill_window(date(2026, 11, 20)) == date(2026, 10, 1)
    assert crypto.fill_window(date(2027, 1, 3)) == date(2026, 12, 1)


def test_the_first_of_the_month_still_fills_the_last_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On 1 Nov the old window was 1 Nov to 31 Oct: no days at all."""
    asked: list[str] = []

    def land(symbol: str, day: str, *, directory: Path) -> tuple[int, bool]:
        asked.append(day)
        return 1440, True

    class Today(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Today:
            return cls(2026, 11, 1, 6, 0, tzinfo=UTC)

    monkeypatch.setattr(crypto, "land_day", land)
    monkeypatch.setattr(crypto, "datetime", Today)
    landed = {f"BTCUSDT-1m-2026-10-{d:02d}.jsonl.gz" for d in range(1, 30)}
    count, _, missing = crypto.fill_days(["BTCUSDT"], directory=tmp_path, landed=landed)
    assert asked == ["2026-10-30", "2026-10-31"]
    assert count == 2
    assert missing == []


def test_days_inside_a_landed_month_are_not_asked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def land(symbol: str, day: str, *, directory: Path) -> tuple[int, bool]:
        asked.append(day)
        return 1440, True

    class Today(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Today:
            return cls(2026, 11, 3, 6, 0, tzinfo=UTC)

    monkeypatch.setattr(crypto, "land_day", land)
    monkeypatch.setattr(crypto, "datetime", Today)
    landed = {"BTCUSDT-1m-2026-10.jsonl.gz", "BTCUSDT-1m-2026-11-01.jsonl.gz"}
    crypto.fill_days(["BTCUSDT"], directory=tmp_path, landed=landed)
    assert asked == ["2026-11-02"]
