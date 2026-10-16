from datetime import date, timedelta

from eulerlab.intraday import company_github_screen as screen
from eulerlab.intraday import india_papers as ip


def _day(day_offset: int, close: list[float], volume: list[float]) -> ip.Day:
    open_ = list(close)
    high = [value + 0.1 for value in close]
    low = [value - 0.1 for value in close]
    return ip.Day(
        day=date(2024, 1, 2) + timedelta(days=day_offset),
        open_=tuple(open_),
        high=tuple(high),
        low=tuple(low),
        close=tuple(close),
        volume=tuple(volume),
        last=len(close) - 1,
    )


def test_profile_for_day_is_only_attached_to_later_session() -> None:
    first = _day(0, [100.0] * ip.MINUTES, [100.0] * ip.MINUTES)
    second = _day(1, [101.0] * ip.MINUTES, [100.0] * ip.MINUTES)

    profiles = screen._profiles([first, second])

    assert first.day not in profiles
    assert profiles[second.day] == (100.0, 100.0, 100.0)


def test_volume_exhaustion_requires_new_low_and_submedian_volume() -> None:
    closes = [100.0] * ip.MINUTES
    volumes = [100.0] * ip.MINUTES
    closes[30] = 99.0
    volumes[30] = 10.0
    day = _day(0, closes, volumes)

    signal = screen._volume_exhaustion("TEST", day, None, {})

    assert signal == [
        {
            "direction": 1,
            "entry": 31,
            "exit": 41,
            "signal": "new 20-minute low on below-median volume",
        }
    ]


def test_time_adaptive_selection_uses_only_named_training_segments() -> None:
    modes = {"open": "reversion", "midday": "momentum", "late": "momentum"}
    closes = [100.0 + minute * 0.03 for minute in range(ip.MINUTES)]
    day = _day(0, closes, [100.0] * ip.MINUTES)

    signals = screen._time_adaptive("TEST", day, None, modes)

    assert len(signals) == 3
    assert signals[0]["signal"] == "open:reversion"
    assert signals[0]["direction"] == -1
    assert all(signal["exit"] - signal["entry"] == 5 for signal in signals)
