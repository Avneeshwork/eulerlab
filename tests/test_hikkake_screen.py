from __future__ import annotations

import pytest

from eulerlab.strategies.studies import hikkake as hs
from eulerlab.strategies.studies.inside_bar import BAR_MINUTES, Bar


def _bar(start: int, high: float, low: float, *, open_: float | None = None) -> Bar:
    return Bar(start, (high + low) / 2 if open_ is None else open_, high, low, (high + low) / 2, 1)


def test_setup_recognizes_bullish_and_bearish_hikkake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hs, "_atr", lambda bars, index: 1.0)
    bullish = [_bar(5, 10, 8), _bar(10, 9.5, 8.5), _bar(15, 9.4, 8.4)]
    bearish = [_bar(5, 10, 8), _bar(10, 9.5, 8.5), _bar(15, 9.6, 8.6)]

    long_setup = hs._setup(bullish, 2)
    short_setup = hs._setup(bearish, 2)

    assert long_setup is not None and long_setup["direction"] == 1
    assert long_setup["trigger"] == 9.55
    assert short_setup is not None and short_setup["direction"] == -1
    assert short_setup["trigger"] == 8.45


def test_entry_expires_after_three_bars() -> None:
    bars = [_bar(index * BAR_MINUTES, 10, 9) for index in range(6)]
    setup = {
        "direction": 1,
        "setup_index": 1,
        "trigger": 11,
        "pattern_start": 5,
        "atr": 1,
    }

    assert hs._entry(bars, setup) is None


def test_entry_stop_uses_pattern_through_trigger_bar_extreme() -> None:
    bars = [
        _bar(0, 10, 8),
        _bar(5, 9.5, 8.5),
        _bar(10, 9.4, 8.4),
        _bar(15, 9.5, 8.2),
        _bar(20, 9.8, 8.1, open_=9.6),
        _bar(25, 9.9, 8.0),
    ]
    setup = {
        "direction": 1,
        "setup_index": 2,
        "trigger": 9.55,
        "pattern_start": 5,
        "atr": 10,
    }

    trade = hs._entry(bars, setup)

    assert trade is not None
    assert trade["entry"] == 9.6
    assert trade["stop"] == pytest.approx(
        8.05
    )  # Full-pattern stop is tighter than the distant 6 x ATR stop.


def test_trigger_bar_that_also_hits_stop_is_marked_stop_first() -> None:
    bars = [
        _bar(0, 10, 8),
        _bar(5, 9.5, 8.5),
        _bar(10, 9.4, 8.4),
        _bar(15, 9.8, 7.8),
    ]
    setup = {
        "direction": 1,
        "setup_index": 2,
        "trigger": 9.55,
        "pattern_start": 5,
        "atr": 0.2,
    }

    trade = hs._entry(bars, setup)

    assert trade is not None
    assert trade["trigger_bar_stop_first"] == 1
