"""Research 154: the move-versus-cost map and the two minute scalps (H-0042, H-0043)."""

from __future__ import annotations

from datetime import date

import numpy as np

from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import move_cost_map as moves
from eulerlab.strategies.studies import minute_scalp as scalp

N = 375


def _day(
    closes: list[float], volumes: list[float] | None = None, when: date = date(2023, 5, 4)
) -> ip.Day:
    closes = closes + [closes[-1]] * (N - len(closes))
    volume = (volumes or []) + [100.0] * (N - len(volumes or []))
    opens = tuple(closes)
    return ip.Day(when, opens, opens, opens, tuple(closes), tuple(volume), N - 1)


def test_the_map_counts_moves_beyond_the_cost_by_half_hour() -> None:
    closes = [100.0] * N
    closes[10] = 100.5  # a 50 bps one-minute move in the first half-hour
    found = moves.measure([_day(closes)])
    one = moves.HORIZONS.index(1)
    assert found.beyond[one][0] == 2  # up at minute 10, back down at minute 11
    assert found.beyond[one][1:].sum() == 0
    assert np.isclose(found.total[one][0], 50.0 + 10_000 * (1 - 100 / 100.5))


def test_a_heavy_volume_shock_is_faded_at_the_next_open() -> None:
    closes = [100.0] * 60 + [101.5] + [101.0] * 40
    volumes = [100.0] * 60 + [1_000.0]
    signal = scalp.shock(_day(closes, volumes))
    assert signal is not None
    assert signal.minute == 60 and signal.direction == -1
    assert signal.entry_minute == 61 and signal.exit_minute == 61 + scalp.HOLD


def test_a_shock_on_ordinary_volume_is_not_traded() -> None:
    closes = [100.0] * 60 + [101.5]
    assert scalp.shock(_day(closes, [100.0] * 61)) is None


def test_round_levels_follow_the_price() -> None:
    assert scalp.step_for(2_340.0) == 100.0
    assert scalp.step_for(456.0) == 10.0
    assert scalp.step_for(56.0) is None


def test_the_first_crossing_after_0920_is_followed() -> None:
    closes = [995.0] * 3 + [1_001.0] * 3 + [998.0] * 5 + [1_003.0] * 50
    # 995 -> 1001 at minute 3 is before 09:20; 1001 -> 998 at minute 6 is the first counted.
    assert scalp.first_cross(_day(closes), 10.0) == (6, -1)


def test_at_most_ten_stock_trades_a_day_earliest_first() -> None:
    day = date(2023, 5, 4)
    marks = {
        f"S{i:02d}": {day: scalp.Signal(20 + i, 1, 21 + i, 100.0, 36 + i, 101.0)} for i in range(12)
    }
    run = scalp.evaluate_stocks("t", marks, [day])
    assert run["trades"] == 10
    assert {t["symbol"] for t in run["trade_log"]} == {f"S{i:02d}" for i in range(10)}
    assert set(run["net_halves"]) == {"before_2024", "2024"}
