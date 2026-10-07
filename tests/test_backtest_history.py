"""The windows a strategy sees, checked against the code they replaced.

`HistoryWindows` reuses the previous rebalance's adjusted rows instead of
adjusting every window from scratch. That is only allowed if it changes
nothing, so these tests keep the original per-call walk — verbatim from the
engines before the change — as the reference, and require bit-for-bit equal
floats on histories built to hit every branch: several actions per
instrument, two on one day, actions before the first row and after the last,
an instrument whose key changes, and dates visited forwards, backwards,
repeatedly and with jumps.
"""

from __future__ import annotations

import random
from bisect import bisect_right
from datetime import date, timedelta

import pytest

from eulerlab.backtest.history import HistoryWindows, back_adjusted
from eulerlab.features.panel import PanelRow


def _reference(
    histories: dict[str, list[PanelRow]],
    events: dict[str, list[tuple[date, float]]],
    lookback: int | None,
    today: date,
) -> dict[str, list[PanelRow]]:
    """The engines' `_view_history` as it was, kept as the oracle."""
    out: dict[str, list[PanelRow]] = {}
    for symbol, rows_ in histories.items():
        ordered = [row.day for row in rows_]
        end = bisect_right(ordered, today)
        if end == 0:
            continue
        start = max(0, end - lookback) if lookback else 0
        window = rows_[start:end]
        knowable = [e for e in events.get(window[-1].isin, []) if e[0] <= today]
        if not knowable:
            out[symbol] = window
            continue
        adjusted: list[PanelRow] = []
        cumulative = 1.0
        cursor = len(knowable) - 1
        for row in reversed(window):
            while cursor >= 0 and knowable[cursor][0] > row.day:
                cumulative *= knowable[cursor][1]
                cursor -= 1
            adjusted.append(row.adjusted(cumulative))
        adjusted.reverse()
        out[symbol] = adjusted
    return out


def _exact(view: dict[str, list[PanelRow]]) -> dict[str, list[PanelRow]]:
    """The view as plain data. Rows compare field by field with `==`, which
    for floats is bit-for-bit: 0.1 + 0.2 and 0.3 count as different."""
    return dict(view)


def _world(
    seed: int,
) -> tuple[dict[str, list[PanelRow]], dict[str, list[tuple[date, float]]], list[date]]:
    rng = random.Random(seed)
    start = date(2016, 1, 1)
    calendar = [
        start + timedelta(days=i) for i in range(400) if (start + timedelta(days=i)).weekday() < 5
    ]
    histories: dict[str, list[PanelRow]] = {}
    events: dict[str, list[tuple[date, float]]] = {}
    factors = (2.0, 1.5, 10.0, 1.1, 3.0, 0.5)
    for n in range(14):
        symbol = f"S{n:02d}"
        key = f"INE{n:04d}X01"
        first = rng.randrange(0, 120)
        last = rng.randrange(first + 30, len(calendar))
        price = 100.0 + n
        rows: list[PanelRow] = []
        for i in range(first, last):
            if rng.random() < 0.05:
                continue  # a day the symbol did not print
            price *= 1 + rng.gauss(0, 0.02)
            # One instrument is re-keyed halfway: the window's last row decides
            # which instrument's actions apply.
            isin = key if not (n == 5 and i > (first + last) // 2) else "INE9999X01"
            rows.append(
                PanelRow(
                    calendar[i],
                    symbol,
                    price,
                    1000.0 + i,
                    price * 1000,
                    isin,
                    0.0,
                    price * 0.99,
                    price * 1.01,
                    price * 0.98,
                )
            )
        histories[symbol] = rows
        if n % 4 == 3:
            continue  # some instruments never have an action
        dates = sorted(rng.sample(range(len(calendar)), rng.randrange(1, 6)))
        series = [(calendar[i], rng.choice(factors)) for i in dates]
        if n == 2:
            series.append((series[0][0], 4.0))  # two actions on one day
        if n == 6:
            series.append((calendar[0] - timedelta(days=30), 2.0))  # before any row
        if n == 7:
            series.append((calendar[-1] + timedelta(days=30), 5.0))  # after every row
        events[key] = sorted(series)
    events["INE9999X01"] = [(calendar[-80], 2.0), (calendar[-30], 1.5)]
    return histories, events, calendar


def _frozen(
    events: dict[str, list[tuple[date, float]]],
) -> dict[str, tuple[tuple[date, float], ...]]:
    return {key: tuple(series) for key, series in events.items()}


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("lookback", [None, 1, 7, 60])
def test_windows_match_the_original_walk_rebalance_by_rebalance(
    seed: int, lookback: int | None
) -> None:
    histories, events, calendar = _world(seed)
    days = {symbol: [row.day for row in rows] for symbol, rows in histories.items()}
    windows = HistoryWindows(histories, days, lookback, _frozen(events))
    for step in (21, 2):
        for today in calendar[::step]:
            assert _exact(windows.at(today)) == _exact(
                _reference(histories, events, lookback, today)
            )


@pytest.mark.parametrize("seed", range(4))
def test_windows_match_when_visited_out_of_order(seed: int) -> None:
    """A caller is not obliged to walk forwards: backwards, repeats and jumps
    must all give the window adjusted from scratch."""
    histories, events, calendar = _world(seed)
    days = {symbol: [row.day for row in rows] for symbol, rows in histories.items()}
    windows = HistoryWindows(histories, days, 40, _frozen(events))
    rng = random.Random(seed)
    visits = [rng.choice(calendar) for _ in range(120)]
    visits += visits[:10] + list(reversed(calendar[::17]))
    visits.append(calendar[0] - timedelta(days=1))  # before any data at all
    for today in visits:
        assert _exact(windows.at(today)) == _exact(_reference(histories, events, 40, today))


def test_a_strategy_editing_its_view_cannot_change_the_next_one() -> None:
    histories, events, calendar = _world(1)
    days = {symbol: [row.day for row in rows] for symbol, rows in histories.items()}
    windows = HistoryWindows(histories, days, 30, _frozen(events))
    first = windows.at(calendar[200])
    for rows in first.values():
        rows.clear()
    again = windows.at(calendar[201])
    assert _exact(again) == _exact(_reference(histories, events, 30, calendar[201]))


def test_back_adjusted_divides_by_every_later_action_known_or_not() -> None:
    day = date(2020, 1, 1)
    rows = [
        PanelRow(day + timedelta(days=i), "X", close, 1.0, 1.0, "K")
        for i, close in enumerate((100.0, 100.0, 50.0, 50.0, 10.0))
    ]
    events = {"K": ((day + timedelta(days=2), 2.0), (day + timedelta(days=4), 5.0))}
    adjusted = back_adjusted(rows, events)
    assert list(adjusted.values()) == [10.0, 10.0, 10.0, 10.0, 10.0]
    assert back_adjusted(rows, {}) == {row.day: row.close for row in rows}
    assert back_adjusted([], events) == {}
