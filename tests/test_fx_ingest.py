"""FX minute bars from Dukascopy's tick feed.

The tests worth having here are about the wire format, because nothing in it is
self-describing: a zero-indexed month and a per-pair price scale are both silent
failures that produce plausible-looking wrong numbers.
"""

from __future__ import annotations

import gzip
import json
import lzma
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from eulerlab.ingest import fx


def _tick(ms: int, ask: int, bid: int, ask_volume: float = 1.0, bid_volume: float = 1.0) -> bytes:
    return fx.TICK_STRUCT.pack(ms, ask, bid, ask_volume, bid_volume)


def _payload(ticks: bytes) -> bytes:
    return lzma.compress(ticks, format=lzma.FORMAT_ALONE)


# --- the wire format --------------------------------------------------------


def test_the_month_in_the_url_is_zero_indexed() -> None:
    """January is 00 and December is 11. Nothing in the URL says so, and an
    off-by-one here fetches a different month's data rather than failing."""
    january = fx.hour_url("EURUSD", datetime(2024, 1, 15, 10, tzinfo=UTC))
    december = fx.hour_url("EURUSD", datetime(2024, 12, 15, 10, tzinfo=UTC))
    assert "/2024/00/15/10h_ticks.bi5" in january
    assert "/2024/11/15/10h_ticks.bi5" in december


def test_jpy_pairs_use_a_different_price_scale() -> None:
    """A wrong scale on EURUSD is obvious at a glance. On USDJPY it is not —
    155.0 and 1.55 are both numbers someone might accept."""
    assert fx.point_scale("EURUSD") == 1e5
    assert fx.point_scale("GBPUSD") == 1e5
    assert fx.point_scale("USDJPY") == 1e3
    assert fx.point_scale("EURJPY") == 1e3


def test_ticks_decode_to_real_prices() -> None:
    hour = datetime(2024, 6, 3, 9, tzinfo=UTC)
    payload = _payload(_tick(0, 108_500, 108_490) + _tick(30_000, 108_520, 108_515))
    ticks = fx.decode_hour(payload, "EURUSD", hour)
    assert len(ticks) == 2
    ts, bid, ask, _volume = ticks[0]
    assert ts == hour
    assert bid == pytest.approx(1.08490)
    assert ask == pytest.approx(1.08500)


def test_a_jpy_tick_decodes_at_its_own_scale() -> None:
    hour = datetime(2024, 6, 3, 9, tzinfo=UTC)
    ticks = fx.decode_hour(_payload(_tick(0, 155_120, 155_100)), "USDJPY", hour)
    _ts, bid, ask, _volume = ticks[0]
    assert bid == pytest.approx(155.100)
    assert ask == pytest.approx(155.120)


def test_an_empty_hour_is_a_real_answer_not_a_failure() -> None:
    """The feed returns nothing for hours the market was shut, and every
    weekend is one. Raising would make a normal Saturday look like an outage."""
    assert fx.decode_hour(b"", "EURUSD", datetime(2024, 6, 2, 3, tzinfo=UTC)) == []


def test_corrupt_compression_yields_nothing_rather_than_raising() -> None:
    assert fx.decode_hour(b"not lzma at all", "EURUSD", datetime(2024, 6, 3, 9, tzinfo=UTC)) == []


# --- resampling -------------------------------------------------------------


def test_ticks_group_into_minute_bars_on_the_mid() -> None:
    """OHLC is built from the mid. A bar of bids and a bar of asks are
    different series, and mixing them is a spread-wide error that never
    surfaces as an exception."""
    base = datetime(2024, 6, 3, 9, tzinfo=UTC)
    ticks = [
        (base, 1.0800, 1.0802, 1.0),
        (base.replace(second=20), 1.0810, 1.0812, 2.0),
        (base.replace(second=50), 1.0795, 1.0797, 3.0),
        (base.replace(minute=1), 1.0805, 1.0807, 4.0),
    ]
    bars = fx.to_minutes(ticks)
    assert len(bars) == 2
    first = bars[0]
    assert first.open == pytest.approx(1.0801)
    assert first.high == pytest.approx(1.0811)
    assert first.low == pytest.approx(1.0796)
    assert first.close == pytest.approx(1.0796)
    assert first.ticks == 3
    assert first.volume == pytest.approx(6.0)
    assert first.mean_spread == pytest.approx(0.0002)


def test_bars_come_out_in_time_order() -> None:
    base = datetime(2024, 6, 3, 9, tzinfo=UTC)
    ticks = [
        (base.replace(minute=5), 1.08, 1.0802, 1.0),
        (base.replace(minute=1), 1.08, 1.0802, 1.0),
        (base.replace(minute=3), 1.08, 1.0802, 1.0),
    ]
    stamps = [b.ts for b in fx.to_minutes(ticks)]
    assert stamps == sorted(stamps)


# --- storage ----------------------------------------------------------------


def test_a_landed_day_round_trips(tmp_path: Path) -> None:
    day = date(2024, 6, 3)
    path = fx.day_path("EURUSD", day, root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bar = fx.Bar(
        ts=datetime(2024, 6, 3, 9, tzinfo=UTC),
        open=1.08,
        high=1.081,
        low=1.079,
        close=1.0805,
        ticks=42,
        volume=7.5,
        mean_spread=0.00012,
    )
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(bar.to_row()) + "\n")

    back = fx.read_day("EURUSD", day, root=tmp_path)
    assert len(back) == 1
    assert back[0].close == pytest.approx(1.0805)
    assert back[0].ticks == 42


def test_a_day_never_landed_reads_as_empty(tmp_path: Path) -> None:
    assert fx.read_day("EURUSD", date(2024, 6, 3), root=tmp_path) == []


def test_landing_a_day_twice_costs_nothing(tmp_path: Path) -> None:
    """What makes a ten-year backfill restartable. Without it a resumed run
    refetches everything it already has."""
    day = date(2024, 6, 3)
    path = fx.day_path("EURUSD", day, root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        gzip.compress(
            b'{"ts": "2024-06-03T09:00:00+00:00", "open": 1.0, '
            b'"high": 1.0, "low": 1.0, "close": 1.0, "ticks": 1, '
            b'"volume": 1.0, "mean_spread": 0.0}\n'
        )
    )
    count, had = fx.land_day("EURUSD", day, root=tmp_path)
    assert had is True
    assert count == 0


def test_the_top_ten_pairs_are_dollar_heavy() -> None:
    """Six USD legs is not an oversight. The dollar is on one side of roughly
    88% of all FX trades, so a list spread evenly across currencies would be a
    different and less liquid universe."""
    assert len(fx.PAIRS) == 10
    assert sum(1 for p in fx.PAIRS if "USD" in p) >= 6
    assert len(set(fx.PAIRS)) == 10


def test_weekends_are_not_fetched() -> None:
    """FX is shut and the feed has no files, so a weekend is 48 wasted
    requests per pair."""
    from eulerlab.ingest.fx_backfill import days_between

    days = days_between(date(2024, 6, 1), date(2024, 6, 10))
    assert all(d.weekday() < 5 for d in days)
    assert date(2024, 6, 1) not in days
