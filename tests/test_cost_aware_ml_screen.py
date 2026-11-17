from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("sklearn")

from eulerlab.intraday import india_papers as ip
from eulerlab.strategies.studies.cost_aware_ml import _records


def _day(session: date) -> ip.Day:
    size = 376
    opens = tuple(100.0 * (1.0 + 0.0002 * minute) for minute in range(size))
    closes = opens
    highs = tuple(value * 1.0001 for value in closes)
    lows = tuple(value * 0.9999 for value in closes)
    volumes = tuple(1000.0 for _ in range(size))
    return ip.Day(session, opens, highs, lows, closes, volumes, 355)


def test_cost_aware_labels_use_delayed_same_session_open_fills() -> None:
    frame = _records([_day(date(2024, 1, 2))])
    labeled = frame.dropna(subset=["label"])

    assert int(labeled.iloc[0]["minute"]) == 1
    assert int(labeled.iloc[0]["entry_minute"]) == 2
    assert int(labeled.iloc[0]["exit_minute"]) == 32
    assert int(labeled.iloc[-1]["minute"]) == 324
    assert int(labeled.iloc[-1]["exit_minute"]) == 355
    assert set(labeled["label"].astype(int)) == {1}


def test_cost_aware_targets_do_not_cross_overnight() -> None:
    frame = _records([_day(date(2024, 1, 2)), _day(date(2024, 1, 3))])

    assert frame.loc[frame["minute"] == 324, "label"].notna().all()
    assert frame.loc[frame["minute"] == 325, "label"].isna().all()
    assert len(frame.loc[frame["day"] == date(2024, 1, 3)]) == 355
