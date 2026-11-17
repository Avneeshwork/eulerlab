"""Research 159: overnight-daytime tug-of-war rules (H-0066 to H-0070)."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.intraday import india_papers as ip
from eulerlab.strategies.studies import tug_of_war as tug
from eulerlab.strategies.studies.overnight_reversal import Mark

N = 375


def test_stock_ranks_count_overnight_up_daytime_down_days() -> None:
    start = date(2023, 1, 2)
    marks = {}
    for i in range(22):
        # Even days: up overnight, down in the day. Odd days: flat.
        if i % 2 == 0:
            marks[start + timedelta(days=i)] = Mark(0.01, 5, 100.0, 355, 99.0)
        else:
            marks[start + timedelta(days=i)] = Mark(0.0, 5, 100.0, 355, 100.0)
    _, counts, month = tug.stock_ranks({"X": marks})
    day = start + timedelta(days=20)
    ((count, symbol, _),) = counts[day]
    assert symbol == "X" and count == 10.0
    ((ret, _, _),) = month[day]
    # Ten days of (1.01 x 0.99) and ten flat days.
    assert abs(ret - (1.01 * 0.99) ** 10 + 1) < 1e-12


def test_index_extremes_short_after_unusually_strong_overnight_gains() -> None:
    days = list(range(300))
    stat: list[float | None] = [None] * 20
    stat += [0.001 * (i % 10) for i in range(279)]
    stat.append(1.0)
    dates = [date(2022, 1, 3) + timedelta(days=i) for i in days]
    signals = tug._extreme_signals(dates, stat, high=-1, low=1)
    assert signals[dates[-1]] == -1


def _index_day(when: date, open_: float, close: float) -> ip.Day:
    closes = [close] * N
    opens: list[float | None] = [open_]
    opens += [close] * (N - 1)
    return ip.Day(
        when, tuple(opens), tuple(closes), tuple(closes), tuple(closes), tuple([0.0] * N), N - 1
    )


def test_nifty_series_splits_overnight_and_daytime() -> None:
    days = [_index_day(date(2023, 5, 3), 100.0, 100.0), _index_day(date(2023, 5, 4), 101.0, 100.0)]
    sessions, overnight, daytime = tug.nifty_series(days)
    assert sessions == [date(2023, 5, 4)]
    assert abs(overnight[0] - 0.01) < 1e-12 and abs(daytime[0] - (100 / 101 - 1)) < 1e-12
