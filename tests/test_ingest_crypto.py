"""Parsing Binance's minute archive, and knowing when a month is short.

Crypto is the one asset class where completeness is exactly checkable: no
holidays, no close, 1,440 bars in every day. Most of these tests lean on that.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from eulerlab.ingest import crypto


def _zip(rows: list[list[object]], *, header: bool = False) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if header:
        writer.writerow(
            [
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_volume",
                "count",
            ]
        )
    for row in rows:
        writer.writerow(row)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("BTCUSDT-1m-2024-01.csv", buffer.getvalue())
    return out.getvalue()


def _row(ms: int, close: float = 100.0) -> list[object]:
    return [ms, 99.0, 101.0, 98.0, close, 5.0, ms + 59999, 500.0, 42]


# --- parsing --------------------------------------------------------------


def test_a_candle_parses_with_its_fields() -> None:
    candles = crypto.parse_month(_zip([_row(1_704_067_200_000)]))
    assert len(candles) == 1
    candle = candles[0]
    assert candle.open_time == datetime(2024, 1, 1, tzinfo=UTC)
    assert (candle.high, candle.low, candle.close) == (101.0, 98.0, 100.0)
    assert candle.trades == 42


def test_a_header_row_is_skipped_not_parsed() -> None:
    """Binance ships a header on newer months and not on older ones. Assuming
    either way silently drops a candle or crashes."""
    assert len(crypto.parse_month(_zip([_row(1_704_067_200_000)], header=True))) == 1


def test_microsecond_timestamps_are_detected() -> None:
    """Binance switched open_time from ms to microseconds in 2025. A wrong
    unit puts the whole month in 1970 or in 55,000 AD — neither of which is
    visible in a row count."""
    micros = 1_704_067_200_000_000
    candle = crypto.parse_month(_zip([_row(micros)]))[0]
    assert candle.open_time.year == 2024


def test_knowledge_time_is_the_bars_close_not_its_open() -> None:
    """A strategy standing at 10:00 may not see the 10:00 bar — it is still
    inside it. The bar becomes knowable when it closes."""
    candle = crypto.parse_month(_zip([_row(1_704_067_200_000)]))[0]
    assert (candle.knowledge_time - candle.open_time).total_seconds() == 60


# --- completeness ---------------------------------------------------------


def test_a_complete_month_has_1440_bars_a_day(tmp_path: Path) -> None:
    """Only checkable because crypto never closes. In equities a missing bar
    might be a holiday; here it is unambiguously missing."""
    path = crypto.month_path("BTCUSDT", "2024-01", directory=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import gzip
    import json

    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for _ in range(31 * crypto.MINUTES_PER_DAY):
            handle.write(json.dumps({"symbol": "BTCUSDT"}) + "\n")

    check = crypto.verify_month("BTCUSDT", "2024-01", directory=tmp_path)
    assert check.expected == 31 * 1440
    assert check.complete
    assert check.missing == 0


def test_a_short_month_reports_how_many_minutes_are_gone(tmp_path: Path) -> None:
    path = crypto.month_path("BTCUSDT", "2024-02", directory=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import gzip
    import json

    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for _ in range(1000):
            handle.write(json.dumps({"symbol": "BTCUSDT"}) + "\n")

    check = crypto.verify_month("BTCUSDT", "2024-02", directory=tmp_path)
    assert check.expected == 29 * 1440, "2024 is a leap year"
    assert not check.complete
    assert check.missing == 29 * 1440 - 1000


def test_an_absent_month_is_wholly_missing_not_complete(tmp_path: Path) -> None:
    check = crypto.verify_month("BTCUSDT", "2024-03", directory=tmp_path)
    assert check.candles == 0
    assert not check.complete


# --- the universe ---------------------------------------------------------


def test_stablecoins_are_excluded() -> None:
    """A stablecoin's USDT pair is not a coin — it is an exchange rate between
    two claims on the same dollar."""
    for ticker in ("USDC", "FDUSD", "RLUSD", "DAI"):
        assert ticker in crypto.STABLECOINS
    assert "BTC" not in crypto.STABLECOINS
    assert "ETH" not in crypto.STABLECOINS


def test_months_between_is_inclusive_at_both_ends() -> None:
    months = crypto.months_between(date(2023, 11, 15), date(2024, 2, 3))
    assert months == ["2023-11", "2023-12", "2024-01", "2024-02"]


def test_a_single_month_range_yields_one_month() -> None:
    assert crypto.months_between(date(2024, 5, 2), date(2024, 5, 28)) == ["2024-05"]


def test_the_recent_gap_is_named_not_hidden() -> None:
    """The monthly archive lags, so a run today lands nothing for the current
    month. A caller reading 'up to today' is really reading to the last
    month-end, and is entitled to know that."""
    start, end = crypto.recent_gap()
    assert start.day == 1
    assert start <= end


@pytest.mark.parametrize("bad", ["", "not-a-zip"])
def test_a_corrupt_archive_raises_rather_than_returning_nothing(bad: str) -> None:
    """Zero candles from a month that should have tens of thousands is a
    failure, not an empty month — so it must raise rather than return []."""
    with pytest.raises(zipfile.BadZipFile):
        crypto.parse_month(bad.encode())


# --- cross-source reconciliation -------------------------------------------


class _FakeExchange:
    """A venue that returns whatever it is told to, including wrong periods."""

    def __init__(self, closes: list[float] | None = None, *, shift_ms: int = 0) -> None:
        # A list of CLOSES, not of rows — the fake builds the OHLCV rows around
        # them. The annotation said list[list[object]] and was simply wrong.
        self._closes = closes or []
        self._shift = shift_ms

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int | None = None, limit: int | None = None
    ) -> list[list[object]]:
        base = (since or 0) + self._shift
        return [
            [base + i * 60_000, 1.0, 1.0, 1.0, close, 1.0] for i, close in enumerate(self._closes)
        ]


def _land(tmp_path: Path, symbol: str, ym: str, closes: list[float]) -> None:
    import gzip
    import json
    from datetime import timedelta

    path = crypto.month_path(symbol, ym, directory=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for i, close in enumerate(closes):
            when = start + timedelta(minutes=i)
            handle.write(
                json.dumps(
                    {
                        "symbol": symbol,
                        "open": close,
                        "high": close,
                        "low": close,
                        "close": close,
                        "volume": 1.0,
                        "trades": 1,
                        "event_time": when.isoformat(),
                        "knowledge_time": (when + timedelta(minutes=1)).isoformat(),
                    }
                )
                + "\n"
            )


def test_two_venues_quoting_the_same_asset_agree(tmp_path: Path) -> None:
    from eulerlab.quality import crypto_reconcile as reconcile

    _land(tmp_path, "BTCUSDT", "2024-01", [100.0] * 10)
    result = reconcile.compare(
        "BTCUSDT",
        "2024-01",
        _FakeExchange([100.05] * 10),
        samples=1,
        per_sample=10,
        directory=tmp_path,
    )
    assert result.usable
    assert result.agrees
    assert result.median_diff_pct < 0.5


def test_a_venue_that_ignores_since_is_unusable_not_disagreeing(tmp_path: Path) -> None:
    """The trap that would make this whole check worthless.

    Kraken returns 2026 bars when asked for 2024, with no error. Comparing them
    reports a ~70% 'disagreement' that is entirely a timestamp bug in the
    REFERENCE — and the natural reading of that number is 'Binance is wrong'.
    """
    from eulerlab.quality import crypto_reconcile as reconcile

    _land(tmp_path, "BTCUSDT", "2024-01", [100.0] * 10)
    two_years = 2 * 365 * 24 * 60 * 60 * 1000
    result = reconcile.compare(
        "BTCUSDT",
        "2024-01",
        _FakeExchange([70000.0] * 10, shift_ms=two_years),
        samples=1,
        per_sample=10,
        directory=tmp_path,
    )
    assert not result.usable
    assert "ignoring `since`" in result.note
    assert not result.agrees


def test_a_real_price_disagreement_is_reported(tmp_path: Path) -> None:
    from eulerlab.quality import crypto_reconcile as reconcile

    _land(tmp_path, "BTCUSDT", "2024-01", [100.0] * 10)
    result = reconcile.compare(
        "BTCUSDT",
        "2024-01",
        _FakeExchange([150.0] * 10),
        samples=1,
        per_sample=10,
        directory=tmp_path,
    )
    assert result.usable, "the timestamps line up, so this is a genuine comparison"
    assert not result.agrees
    assert result.median_diff_pct > 40


def test_ohlc_violations_are_caught(tmp_path: Path) -> None:
    import gzip
    import json

    from eulerlab.quality import crypto_reconcile as reconcile

    path = crypto.month_path("BADUSDT", "2024-01", directory=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "symbol": "BADUSDT",
                    "open": 5.0,
                    "high": 1.0,
                    "low": 9.0,
                    "close": 5.0,
                    "volume": 1.0,
                    "trades": 1,
                    "event_time": "2024-01-01T00:00:00+00:00",
                    "knowledge_time": "2024-01-01T00:01:00+00:00",
                }
            )
            + "\n"
        )
    problems = reconcile.sanity_checks("BADUSDT", "2024-01", directory=tmp_path)
    assert any("low>high" in p for p in problems)
