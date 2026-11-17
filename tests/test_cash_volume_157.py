"""Research 157: intraday persistence, volume and attention (H-0056 to H-0060)."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.intraday import india_papers as ip
from eulerlab.strategies.studies import cash_volume as vol

N = 375


def _day(
    closes: list[float], *, when: date, volume: float = 100.0, first_hour: float | None = None
) -> ip.Day:
    closes = closes + [closes[-1]] * (N - len(closes))
    prices = tuple(closes)
    volumes = [volume] * N
    if first_hour is not None:
        volumes[: vol.FIRST_HOUR] = [first_hour] * vol.FIRST_HOUR
    return ip.Day(when, prices, prices, prices, prices, tuple(volumes), N - 1)


def _days(n: int, price: float = 200.0, **kw: object) -> list[ip.Day]:
    start = date(2023, 1, 2)
    return [_day([price] * 30, when=start + timedelta(days=i), **kw) for i in range(n)]  # type: ignore[arg-type]


def test_attention_buys_the_minute_after_plus_five_but_not_a_gap_above() -> None:
    day = _day([100.0] * 40 + [105.5] * 10, when=date(2023, 5, 4))
    fill = vol.attention(day, 100.0)
    assert fill is not None and fill.minute == 40 and fill.entry_minute == 41
    assert vol.attention(_day([106.0] * 40, when=date(2023, 5, 4)), 100.0) is None


def test_a_heavy_quiet_first_hour_is_a_shock_and_a_moving_one_is_not() -> None:
    days = _days(15)
    days[-1] = _day([200.0] * 30, when=days[-1].day, first_hour=400.0)
    mark = vol.extract("X", days)[days[-1].day]
    assert mark.volume_ratio == 4.0 and mark.shock_fill is not None
    assert mark.shock_fill.entry_minute == vol.FIRST_HOUR + 1
    moving = _days(15)
    moving[-1] = _day([200.0] * 30 + [210.0] * 40, when=moving[-1].day, first_hour=400.0)
    assert vol.extract("X", moving)[moving[-1].day].shock_fill is None


def test_light_volume_big_days_are_faded_and_heavy_ones_followed() -> None:
    assert vol.split_direction(0.05, 0.5, heavy=2.0, light=1.0) == -1
    assert vol.split_direction(0.05, 2.5, heavy=2.0, light=1.0) == 1
    assert vol.split_direction(-0.05, 2.5, heavy=2.0, light=1.0) == -1
    assert vol.split_direction(0.05, 1.5, heavy=2.0, light=1.0) == 0


def test_persistence_is_the_mean_of_the_previous_twenty_daytime_returns() -> None:
    start = date(2023, 1, 2)
    days = []
    for i in range(22):
        closes = [100.0] * 5 + [101.0] * 400  # 09:20 open 101 -> 15:10 101: zero
        if i < 21:
            closes = [100.0] * 5 + [100.0] + [102.0] * 400  # 100 -> 102: +2%
        days.append(_day(closes, when=start + timedelta(days=i)))
    marks = vol.extract("X", days)
    assert marks[days[20].day].persistence is not None
    assert abs((marks[days[20].day].persistence or 0.0) - 0.02) < 1e-9
