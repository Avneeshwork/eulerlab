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
    """Both sides are stored; the mid is derived per field on read. The high of
    the mid is the mid of the highs, and applying one mid everywhere would
    narrow every bar."""
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
    # From open and close only. The highest ask and the highest bid happen at
    # different instants inside the minute, so their difference is not a spread.
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
        bid_open=1.0799,
        bid_high=1.0809,
        bid_low=1.0789,
        bid_close=1.0804,
        ask_open=1.0801,
        ask_high=1.0811,
        ask_low=1.0791,
        ask_close=1.0806,
        ticks=42,
        volume=7.5,
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


def test_a_spread_never_uses_the_high_or_the_low() -> None:
    """The bug that forced this file's rewrite.

    Averaging (Ask - Bid) across open, high, low and close treats `AskHigh -
    BidHigh` as a spread. It is not: the highest ask and the highest bid occur
    at *different instants* inside the minute, so the difference is a gap
    between two unrelated moments. On real data it went negative, which is
    impossible for a quote and was the clue.

    Here the highs and lows are deliberately crossed. Only open and close are
    contemporaneous, so only they may be used, and the answer must stay
    positive.
    """
    bar = fx.Bar(
        ts=datetime(2024, 6, 3, 9, tzinfo=UTC),
        bid_open=1.0000,
        bid_high=1.0090,
        bid_low=0.9990,
        bid_close=1.0010,
        ask_open=1.0002,
        ask_high=1.0080,
        ask_low=0.9980,
        ask_close=1.0012,
    )
    assert bar.mean_spread == pytest.approx(0.0002)
    assert bar.mean_spread > 0


def test_both_sides_survive_a_round_trip() -> None:
    """Storing a derived mid and discarding bid and ask meant a mistake in the
    derivation could only be fixed by re-fetching ten years."""
    bar = fx.Bar(
        ts=datetime(2024, 6, 3, 9, tzinfo=UTC),
        bid_open=1.0,
        bid_high=1.1,
        bid_low=0.9,
        bid_close=1.05,
        ask_open=1.0002,
        ask_high=1.1002,
        ask_low=0.9002,
        ask_close=1.0502,
        ticks=7,
    )
    back = fx.Bar.from_row(bar.to_row())
    assert back.bid_close == pytest.approx(1.05)
    assert back.ask_close == pytest.approx(1.0502)
    assert back.mean_spread == pytest.approx(bar.mean_spread)
