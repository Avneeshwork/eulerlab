from __future__ import annotations

from datetime import date

from eulerlab.intraday.india_papers import Day
from eulerlab.intraday.screen_common import ema as _ema
from eulerlab.strategies.studies.github_followup import _exit


def test_ema_is_deterministic_and_has_expected_first_value() -> None:
    assert _ema([10.0, 12.0, 12.0], 3) == [10.0, 11.0, 11.5]


def test_same_bar_stop_and_target_resolves_to_stop_first() -> None:
    size = 375
    opens: list[float | None] = [None] * size
    highs: list[float | None] = [None] * size
    lows: list[float | None] = [None] * size
    closes = [100.0] * size
    volumes = [100.0] * size
    opens[30], highs[30], lows[30] = 100.0, 103.0, 98.0
    day = Day(
        day=date(2024, 1, 2),
        open_=tuple(opens),
        high=tuple(highs),
        low=tuple(lows),
        close=tuple(closes),
        volume=tuple(volumes),
        last=374,
    )

    assert _exit(
        day,
        {"direction": 1, "entry_minute": 30, "stop": 99.0, "target": 101.0},
    ) == (30, 99.0, "stop_first")
