"""The decay monitor (ADR-178): a planted dead strategy is caught, healthy ones mostly are not."""

from __future__ import annotations

import random

import pytest

from eulerlab.deploy import decay


def _returns(n: int, mean: float, std: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(mean, std) for _ in range(n)]


BACKTEST = _returns(1500, 0.0015, 0.01, seed=1)  # an annual Sharpe near 2.4


def test_the_alarm_level_holds_its_false_alarm_rate_on_fresh_resamples() -> None:
    base = decay.baseline(BACKTEST)
    assert base is not None
    h = decay.calibrate(BACKTEST, base, false_alarm=0.05, horizon=250)
    assert decay.false_alarm_rate(BACKTEST, base, h, 250) <= 0.10
    # And on new draws from the same process, not only resamples of the one backtest.
    crossed = sum(
        max(decay.path(_returns(250, 0.0015, 0.01, seed=100 + i), base)) >= h for i in range(200)
    )
    assert crossed / 200 <= 0.12


def test_planted_strategies_with_no_edge_left_are_caught_as_often_and_as_fast_as_expected() -> None:
    """Issue #147: the planted strategy is flagged within the number of sessions the monitor says."""
    base = decay.baseline(BACKTEST)
    assert base is not None
    h = decay.calibrate(BACKTEST, base, false_alarm=0.05, horizon=250)
    expected = decay.delay(BACKTEST, base, h, 250)
    median = expected["median_sessions"]
    assert expected["caught"] is not None and median is not None
    assert expected["caught"] > 0.5 and median < 200
    hits = []
    for i in range(200):  # 200 fresh strategies whose live mean is zero
        dead = _returns(250, 0.0, 0.01, seed=500 + i)
        hits.append(next((n + 1 for n, s in enumerate(decay.path(dead, base)) if s >= h), None))
    caught = [n for n in hits if n is not None]
    assert abs(len(caught) / 200 - expected["caught"]) < 0.12
    assert abs(sorted(caught)[len(caught) // 2] - median) < 40
    # Far more dead strategies are caught than healthy ones are wrongly flagged.
    assert len(caught) / 200 > 8 * decay.false_alarm_rate(BACKTEST, base, h, 250)


def test_states_go_healthy_watch_decayed() -> None:
    healthy = decay.read(BACKTEST, _returns(120, 0.0015, 0.01, seed=3)[:40])
    assert healthy.state == "healthy" and healthy.h is not None
    losing = decay.read(BACKTEST, [-0.004] * 60)
    assert losing.state == "decayed" and losing.s >= (losing.h or 0)
    base = decay.baseline(BACKTEST)
    assert base is not None and losing.h is not None
    # Enough bad days to pass the watch level and not the alarm level.
    days = 1
    while decay.path([-0.004] * days, base)[-1] < 0.7 * losing.h:
        days += 1
    assert decay.read(BACKTEST, [-0.004] * days).state == "watch"


def test_slippage_drift_alone_means_watch() -> None:
    live = _returns(60, 0.0015, 0.01, seed=5)
    assert decay.read(BACKTEST, live).state == "healthy"
    assert decay.read(BACKTEST, live, slippage_drift=True).state == "watch"


def test_measured_slippage_lowers_what_is_expected() -> None:
    plain = decay.baseline(BACKTEST)
    net = decay.baseline(BACKTEST, slippage_daily=0.0005)
    assert plain is not None and net is not None
    assert net.mean == pytest.approx(plain.mean - 0.0005) and net.k < plain.k


def test_a_short_backtest_gives_no_verdict() -> None:
    found = decay.read(BACKTEST[:50], [0.0] * 10)
    assert found.state == "too little history" and found.h is None
