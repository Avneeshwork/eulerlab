from __future__ import annotations

from datetime import date

from eulerlab.intraday.github_donchian_screen import _run
from eulerlab.intraday.india_papers import Day


def _day(when: date, *, breakout: bool = False) -> Day:
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    for minute in range(360):
        price = (
            103.0
            if breakout and minute >= 210
            else (102.0 if breakout and minute >= 200 else 100.0)
        )
        opens.append(price)
        closes.append(price)
        highs.append(price + (0.5 if breakout and minute == 204 else 1.0))
        lows.append(price - 1.0)
    return Day(when, tuple(opens), tuple(highs), tuple(lows), tuple(closes), (100.0,) * 360, 359)


def test_donchian_breakout_uses_prior_channel_and_forces_intraday_exit() -> None:
    data = {
        "RELIANCE": [
            _day(date(2023, 12, 27)),
            _day(date(2023, 12, 28)),
            _day(date(2024, 1, 2), breakout=True),
        ]
    }

    result = _run(data)

    assert result["trades"] == 1
    trade = result["trade_log"][0]
    assert trade["entry_minute"] == 205
    assert trade["exit_minute"] == 355
    assert trade["exit_reason"] == "time_exit"
    assert trade["gross_pnl"] > 0
