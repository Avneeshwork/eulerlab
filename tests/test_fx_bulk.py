"""FX minute bars from FXCM's weekly candle files.

The Dukascopy path is correct and unusable at scale: 810 seconds per pair-day
measured over a real run. These tests cover the bulk path that replaces it, and
the one thing that would silently corrupt every timestamp in it.
"""

from __future__ import annotations

import gzip
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from eulerlab.ingest import fx, fx_bulk

HEADER = "DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose"


def _csv(rows: list[str]) -> bytes:
    return gzip.compress("\n".join([HEADER, *rows]).encode())


def test_the_date_is_month_first_not_day_first() -> None:
    """03/06/2016 is the 6th of March here and the 3rd of June elsewhere, and
    nothing in the file says which. Guessing wrong shifts every bar by months
    without any parse ever failing."""
    bars = fx_bulk.parse_week(_csv(["03/06/2016 22:00:00.000,1.1,1.1,1.1,1.1,1.2,1.2,1.2,1.2"]))
    assert len(bars) == 1
    assert bars[0].ts == datetime(2016, 3, 6, 22, 0, tzinfo=UTC)


def test_the_mid_is_taken_per_field() -> None:
    """Not a mid of the closes applied to every field: the high of the mid is
    the mid of the highs, and conflating them narrows every bar."""
    bars = fx_bulk.parse_week(_csv(["01/05/2020 10:00:00.000,1.0,1.4,0.8,1.2,1.2,1.6,1.0,1.4"]))
    bar = bars[0]
    assert bar.open == pytest.approx(1.1)
    assert bar.high == pytest.approx(1.5)
    assert bar.low == pytest.approx(0.9)
    assert bar.close == pytest.approx(1.3)


def test_the_spread_uses_only_the_contemporaneous_points() -> None:
    bars = fx_bulk.parse_week(
        _csv(["01/05/2020 10:00:00.000,1.0,1.0,1.0,1.0,1.0002,1.0002,1.0002,1.0002"])
    )
    assert bars[0].mean_spread == pytest.approx(0.0002)


def test_tick_count_is_zero_because_there_is_none() -> None:
    """FXCM publishes aggregated candles. Deriving a tick count from the bar's
    range would be a fabricated field that reads exactly like a measured one."""
    bars = fx_bulk.parse_week(_csv(["01/05/2020 10:00:00.000,1.0,1.1,0.9,1.05,1.0,1.1,0.9,1.05"]))
    assert bars[0].ticks == 0
    assert bars[0].volume == 0.0


def test_an_unparseable_row_is_dropped_not_defaulted() -> None:
    """A bar with a guessed price is worse than an absent one: the absence is
    visible in the count and the guess is not."""
    bars = fx_bulk.parse_week(
        _csv(
            [
                "01/05/2020 10:00:00.000,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0",
                "garbage,,,,,,,,",
                "01/05/2020 10:01:00.000,x,1.0,1.0,1.0,1.0,1.0,1.0,1.0",
            ]
        )
    )
    assert len(bars) == 1


def test_the_url_carries_pair_year_and_week() -> None:
    url = fx_bulk.week_url("GBPJPY", 2019, 10)
    assert url.endswith("/m1/GBPJPY/2019/10.csv.gz")


# --- storage interoperates with the tick path -------------------------------


def test_a_bulk_week_writes_days_the_tick_reader_can_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One storage layout, two sources. `fx.read_day` must not need to know
    which produced a file."""
    payload = _csv(
        [
            "01/06/2020 10:00:00.000,1.0,1.0,1.0,1.0,1.0002,1.0002,1.0002,1.0002",
            "01/06/2020 10:01:00.000,1.1,1.1,1.1,1.1,1.1002,1.1002,1.1002,1.1002",
            "01/07/2020 10:00:00.000,1.2,1.2,1.2,1.2,1.2002,1.2002,1.2002,1.2002",
        ]
    )
    monkeypatch.setattr(fx_bulk, "_fetch", lambda url, **kw: payload)
    days, bars, _had = fx_bulk.land_week("EURUSD", 2020, 2, root=tmp_path)
    assert days == 2
    assert bars == 3

    back = fx.read_day("EURUSD", date(2020, 1, 6), root=tmp_path)
    assert len(back) == 2
    assert back[0].close == pytest.approx(1.0001)


def test_a_day_already_held_is_not_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What makes the backfill resumable: restarting costs only the weeks in
    flight."""
    payload = _csv(["01/06/2020 10:00:00.000,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0"])
    monkeypatch.setattr(fx_bulk, "_fetch", lambda url, **kw: payload)
    fx_bulk.land_week("EURUSD", 2020, 2, root=tmp_path)
    days, bars, had = fx_bulk.land_week("EURUSD", 2020, 2, root=tmp_path)
    assert days == 0
    assert bars == 0
    assert had is True


def test_a_missing_week_is_an_ordinary_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Week 1 is absent for several years and week 53 for most - the ISO week
    falling outside the year's trading, not a gap in the data."""
    monkeypatch.setattr(fx_bulk, "_fetch", lambda url, **kw: None)
    assert fx_bulk.land_week("EURUSD", 2020, 1, root=tmp_path) == (0, 0, False)
