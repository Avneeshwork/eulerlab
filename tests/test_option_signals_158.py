"""Research 158: option signals, half-hours and overnight winners (H-0061 to H-0065)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from eulerlab.intraday import india_papers as ip
from eulerlab.strategies.studies import option_signal as sig

N = 375


def _day(closes: list[float], when: date) -> ip.Day:
    closes = closes + [closes[-1]] * (N - len(closes))
    prices = tuple(closes)
    return ip.Day(when, prices, prices, prices, prices, tuple([100.0] * N), N - 1)


def test_option_days_find_the_pin_and_the_next_expiry_put_call_ratio(tmp_path: Path) -> None:
    rows = [
        {
            "d": "2023-05-03",
            "fut": [],
            "opt": [
                ["2023-05-04", 18000.0, "CE", None, 1.0, 0.0, 100.0, None],
                ["2023-05-04", 18100.0, "CE", None, 1.0, 0.0, 900.0, None],
                ["2023-05-04", 18100.0, "PE", None, 1.0, 0.0, 500.0, None],
                ["2023-05-11", 18100.0, "CE", None, 1.0, 0.0, 200.0, None],
                ["2023-05-11", 18100.0, "PE", None, 1.0, 0.0, 300.0, None],
            ],
        },
    ]
    path = tmp_path / "opt.jsonl"
    path.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n")
    (day,) = sig.option_days(path, start=date(2023, 1, 1), end=date(2023, 12, 31))
    assert day.pin_for_next[date(2023, 5, 4)] == 18100.0
    # The nearest expiry after 3 May is 4 May: puts 500 over calls 1,000.
    assert day.pcr == 0.5


def test_the_pin_trade_buys_when_the_nifty_is_below_the_strike_at_one() -> None:
    before, today = date(2023, 5, 3), date(2023, 5, 4)
    options = [sig.OptionDay(before, {today: 18100.0}, None), sig.OptionDay(today, {}, None)]
    index = [_day([18000.0] * 10, before), _day([18000.0] * 400, today)]
    etf = [_day([200.0] * 10, before), _day([200.0] * 400, today)]
    ((day, fill),) = sig.pin_trades(index, etf, options)
    assert day == today and fill.direction == 1 and fill.entry_minute == sig.PIN_MINUTE + 1


def test_the_put_call_signal_needs_a_full_year_and_reads_the_extremes() -> None:
    start = date(2022, 1, 3)
    days = [
        sig.OptionDay(start + timedelta(days=i), {}, 1.0 + (i % 10) / 100)
        for i in range(sig.PCR_HISTORY + 2)
    ]
    days[-2] = sig.OptionDay(days[-2].day, {}, 2.0)
    signals = sig.pcr_signals(days)
    assert signals == {days[-1].day: 1}


def test_half_hour_signal_is_yesterdays_return_in_that_half_hour() -> None:
    first = [100.0] * sig.HALF_HOUR + [102.0] * 40  # 14:40 open 102? opens follow closes
    days = [
        _day([100.0] * 400, date(2023, 5, 3)),
        _day(first, date(2023, 5, 4)),
        _day([100.0] * 400, date(2023, 5, 5)),
    ]
    marks = sig.half_hours("X", days)
    assert marks[date(2023, 5, 4)][0] == 0.0
    assert marks[date(2023, 5, 5)][0] is not None
