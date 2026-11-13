"""Rescaling Angel's old minute bars to Kite's level (research 193)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab.ingest.angel_rescale import Factor, bhav_closes, load_factors, measure
from eulerlab.intraday.tweezer import IST, Candle


def _day(day: date, close: float, volume: float = 100.0, minutes: int = 3) -> list[Candle]:
    start = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)
    return [
        Candle(start + timedelta(minutes=i), close, close, close, close, volume)
        for i in range(minutes)
    ]


DAYS = [
    date(2021, 8, 20),
    date(2021, 8, 23),
    date(2021, 8, 24),
    date(2021, 8, 25),
    date(2021, 8, 26),
]


def _pair(drift: float = 0.0, on: int = 2) -> tuple[list[Candle], list[Candle]]:
    kite: list[Candle] = []
    angel: list[Candle] = []
    for i, d in enumerate(DAYS):
        a = 100.0 + i
        angel += _day(d, a, volume=200.0)
        kite += _day(d, a * 0.95 * (1 + (drift if i >= on else 0.0)), volume=170.0)
    return kite, angel


def test_a_constant_ratio_gives_one_factor_and_a_clean_seam() -> None:
    kite, angel = _pair()
    before = _day(date(2021, 8, 18), 99.0, volume=200.0)
    bhav = {date(2021, 8, 18): 2 * 99.0, date(2021, 8, 20): 2 * 100.0}  # unadjusted, same return
    f = measure("ACME", kite, angel, before, bhav)
    assert f.status == "ok"
    assert abs(f.factor - 0.95) < 1e-12 and abs(f.volume_factor - 0.85) < 1e-12
    assert f.seam_return is not None and abs(f.seam_return - (100 / 99 - 1)) < 1e-9
    scaled = f.apply(before[-1])
    assert abs(scaled.close - 99.0 * 0.95) < 1e-9 and abs(scaled.volume - 170.0) < 1e-9


def test_a_ratio_that_wanders_is_refused() -> None:
    kite, angel = _pair(drift=0.02)
    before = _day(date(2021, 8, 18), 99.0)
    f = measure("ACME", kite, angel, before, {})
    assert f.status.startswith("drift")


def test_a_corporate_action_later_in_the_window_does_not_move_the_seam_factor() -> None:
    kite, angel = _pair(drift=0.33, on=4)  # a bonus on the fifth day, one vendor only
    before = _day(date(2021, 8, 18), 99.0)
    bhav = {date(2021, 8, 18): 99.0, date(2021, 8, 20): 100.0}
    f = measure("ACME", kite, angel, before, bhav)
    assert f.status == "ok" and abs(f.factor - 0.95) < 1e-12
    assert abs(f.later_move - 0.33) < 1e-9


def test_a_delisted_name_with_no_kite_series_is_served_as_angel_has_it(tmp_path: Path) -> None:
    from eulerlab.ingest.angel_rescale import run

    angel = _day(date(2021, 8, 20), 50.0)

    def read(tree: str, _s: str, _a: date, _b: date) -> list[Candle]:
        return [] if tree == "kite" else angel

    panel = tmp_path / "p.jsonl"
    panel.write_text("")
    [f] = run(["IDFC"], read, panel=panel, delisted=frozenset({"IDFC"}))
    assert (f.status, f.factor, f.note) == ("ok", 1.0, "Angel only")


def test_a_false_jump_at_the_seam_is_refused() -> None:
    kite, angel = _pair()
    before = _day(date(2021, 8, 18), 99.0)
    bhav = {date(2021, 8, 18): 99.0, date(2021, 8, 20): 90.0}  # NSE says it fell 9%
    f = measure("ACME", kite, angel, before, bhav)
    assert f.status.startswith("seam")


def test_too_little_overlap_is_refused() -> None:
    kite, angel = _pair()
    f = measure("ACME", kite[:3], angel, [], {})
    assert f.status.startswith("only")


def test_only_passing_symbols_are_loaded(tmp_path: Path) -> None:
    good = Factor("A", 0.9, 1.0, 9, 0.001, 0.01, 0.01, "ok")
    bad = Factor("B", 0.9, 1.0, 9, 0.03, 0.01, 0.01, "drift 3.00% over 0.5%")
    path = tmp_path / "f.json"
    from dataclasses import asdict

    path.write_text(json.dumps({"symbols": [asdict(good), asdict(bad)]}))
    assert set(load_factors(path)) == {"A"}
    assert load_factors(tmp_path / "none.json") == {}


def test_bhavcopy_closes_follow_a_rename_by_instrument_key(tmp_path: Path) -> None:
    rows = [
        {"d": "2021-08-18", "s": "ZOMATO", "isin": "INE758T010", "c": 140.0},
        {"d": "2021-08-20", "s": "ZOMATO", "isin": "INE758T010", "c": 138.0},
        {"d": "2026-11-13", "s": "ETERNAL", "isin": "INE758T010", "c": 300.0},
    ]
    panel = tmp_path / "p.jsonl"
    panel.write_text("".join(json.dumps(r) + "\n" for r in rows))
    got = bhav_closes({"ETERNAL"}, {date(2021, 8, 18), date(2021, 8, 20)}, panel)
    assert got == {"ETERNAL": {date(2021, 8, 18): 140.0, date(2021, 8, 20): 138.0}}


class _NoBucket:
    def get_paginator(self, _name: str) -> _NoBucket:
        return self

    def paginate(self, **_kw: object) -> list[dict[str, object]]:
        return [{"Contents": []}]


def test_history_is_served_scaled_and_only_before_kites_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.ingest.kite_minute import Chunk, MinuteStore, candles_to_table
    from eulerlab.intraday import store

    mp = monkeypatch
    kite_root, angel_root = tmp_path / "kite", tmp_path / "angel"
    MinuteStore(kite_root).write(
        Chunk("ACME", 1, date(2021, 8, 19), date(2021, 8, 20)),
        candles_to_table([["2021-08-20T09:15:00+0530", 95.0, 95.0, 95.0, 95.0, 10]]),
    )
    MinuteStore(angel_root).write(
        Chunk("ACME", 1, date(2021, 8, 16), date(2021, 8, 31)),
        candles_to_table(
            [
                ["2021-08-18T09:15:00+0530", 100.0, 100.0, 100.0, 100.0, 20],
                ["2021-08-20T09:15:00+0530", 100.0, 100.0, 100.0, 100.0, 20],  # calibration
            ]
        ),
    )
    mp.setattr(store, "_client", _NoBucket)
    mp.setattr(store, "CACHE", kite_root)
    mp.setattr(store, "HISTORY_CACHE", angel_root)
    factors = {"ACME": Factor("ACME", 0.95, 0.5, 9, 0.0, 0.0, 0.0, "ok")}
    mp.setattr("eulerlab.ingest.angel_rescale.load_factors", lambda: factors)

    plain = store.fetch("ACME")
    assert [c.close for c in plain] == [95.0]
    long = store.fetch("ACME", history=True)
    assert [(c.ts.date(), c.close, c.volume) for c in long] == [
        (date(2021, 8, 18), 95.0, 10.0),
        (date(2021, 8, 20), 95.0, 10.0),
    ]
    mp.setattr("eulerlab.ingest.angel_rescale.load_factors", dict)
    assert len(store.fetch("ACME", history=True)) == 1  # refused symbol: no unscaled history
