"""Crypto and fund history as panel rows.

The point of these adapters is that nothing downstream changes: the same
features, the same two engines, the same cost model and the same battery work
on crypto and mutual funds because the rows are the shape they already expect.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab.features import alt_panel
from eulerlab.features.panel import PanelRow
from eulerlab.ingest import amfi


def _land_crypto(root: Path, symbol: str, closes: list[float]) -> None:
    path = root / symbol / f"{symbol}-1m-2024-01.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for index, close in enumerate(closes):
            when = start + timedelta(minutes=index)
            handle.write(
                json.dumps(
                    {
                        "symbol": symbol,
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


def test_minutes_collapse_into_one_daily_bar(tmp_path: Path) -> None:
    """1,440 minutes in, one bar out — the daily bar is what a daily strategy
    is entitled to see, and keeping the minutes would only invite it to read
    them."""
    _land_crypto(tmp_path, "BTCUSDT", [100.0 + i for i in range(1440)])
    rows = alt_panel.crypto_daily(directory=tmp_path)

    assert len(rows) == 1
    bar = rows[0]
    assert bar.day == date(2024, 1, 1)
    assert bar.close == 100.0 + 1439, "the day's LAST close, not its first"
    assert bar.open == 100.0
    assert bar.high == 100.0 + 1439 + 1
    assert bar.low == 99.0
    assert bar.volume == 1440 * 2.0, "volume sums across the day"


def test_turnover_is_derived_the_same_way_as_equities(tmp_path: Path) -> None:
    """close x volume, not Binance's own quote-volume column. One definition
    across asset classes beats two that nearly agree."""
    _land_crypto(tmp_path, "ETHUSDT", [50.0, 50.0])
    row = alt_panel.crypto_daily(directory=tmp_path)[0]
    assert row.turnover == row.close * row.volume


def test_a_damaged_month_does_not_cost_the_others(tmp_path: Path) -> None:
    """One unreadable file must not lose the other 1,199."""
    _land_crypto(tmp_path, "BTCUSDT", [100.0, 101.0])
    broken = tmp_path / "BTCUSDT" / "BTCUSDT-1m-2024-02.jsonl.gz"
    broken.write_bytes(b"\x1f\x8b\x08\x00not-a-stream")

    rows = alt_panel.crypto_daily(directory=tmp_path)
    assert len(rows) == 1, "the readable month still lands"


def test_the_crypto_panel_is_a_real_panel_row(tmp_path: Path) -> None:
    """Everything downstream depends on this and nothing else asserts it."""
    _land_crypto(tmp_path, "BTCUSDT", [100.0])
    assert isinstance(alt_panel.crypto_daily(directory=tmp_path)[0], PanelRow)


# --- funds -----------------------------------------------------------------


def _land_fund(root: Path, code: str, navs: list[tuple[str, float]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with gzip.open(root / f"{code}.jsonl.gz", "wt", encoding="utf-8") as handle:
        for when, nav in navs:
            handle.write(
                json.dumps(
                    {
                        "scheme_code": code,
                        "nav": nav,
                        "event_time": when,
                        "knowledge_time": when,
                    }
                )
                + "\n"
            )


def test_a_fund_has_no_volume_and_that_is_not_a_placeholder(tmp_path: Path) -> None:
    """Units are created and redeemed at NAV, not matched in a book. A
    liquidity factor on an instrument with no market is not a small effect, it
    is a category error — so the features that read turnover return nothing
    rather than a number."""
    _land_fund(tmp_path, "119551", [("2024-01-01", 100.0), ("2024-01-02", 101.0)])
    rows = alt_panel.fund_daily(directory=tmp_path, direct_growth_only=False)

    assert len(rows) == 2
    assert all(r.volume == 0.0 and r.turnover == 0.0 for r in rows)
    assert rows[0].close == 100.0


def test_a_non_positive_nav_is_dropped(tmp_path: Path) -> None:
    _land_fund(tmp_path, "1", [("2024-01-01", 0.0), ("2024-01-02", 10.0)])
    rows = alt_panel.fund_daily(directory=tmp_path, direct_growth_only=False)
    assert [r.close for r in rows] == [10.0]


def test_limit_samples_the_filtered_set_not_the_alphabetical_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug this caused looked like an empty dataset.

    AMFI issues scheme codes in order and direct plans only became mandatory in
    2013, so every direct-growth scheme sits at the HIGH end of the range.
    Taking the first N files and filtering afterwards returned exactly zero of
    them from 600 files.
    """
    for code in ("100001", "100002", "150001", "150002"):
        _land_fund(tmp_path, code, [("2024-01-01", 10.0)])

    rows = alt_panel.fund_daily(directory=tmp_path, direct_growth_only=False, limit=2)
    assert {r.symbol for r in rows} == {"100001", "100002"}, "unfiltered, the head is correct"

    # With a filter that only the high codes satisfy, `limit` must sample those.
    class _Scheme:
        def __init__(self, code: str) -> None:
            self.scheme_code = code
            self.is_direct_growth = True

    monkeypatch.setattr(amfi, "fetch_universe", lambda: [_Scheme("150001"), _Scheme("150002")])
    filtered = alt_panel.fund_daily(directory=tmp_path, limit=2)
    assert {r.symbol for r in filtered} == {"150001", "150002"}


def test_coverage_reports_the_thinnest_series(tmp_path: Path) -> None:
    """A panel whose thinnest symbol has 20 rows is not a panel of its fattest."""
    _land_fund(tmp_path, "1", [("2024-01-01", 10.0)])
    _land_fund(tmp_path, "2", [("2024-01-01", 10.0), ("2024-01-02", 11.0)])
    stats = alt_panel.coverage(alt_panel.fund_daily(directory=tmp_path, direct_growth_only=False))
    assert stats["symbols"] == 2
    assert stats["thinnest"] == 1
    assert stats["fattest"] == 2


def test_an_empty_panel_reports_zero_rather_than_raising() -> None:
    assert alt_panel.coverage([])["rows"] == 0
