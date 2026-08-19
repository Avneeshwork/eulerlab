"""The feature library: signs, insufficient history, and purity."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.features import trials
from eulerlab.features.library import BY_NAME, LIBRARY
from eulerlab.features.panel import PanelRow


def _history(
    closes: list[float], *, volume: float = 1000.0, turnover: float = 100000.0
) -> list[PanelRow]:
    start = date(2024, 1, 1)
    return [
        PanelRow(
            day=start + timedelta(days=i), symbol="ACME", close=c, volume=volume, turnover=turnover
        )
        for i, c in enumerate(closes)
    ]


def _rising(n: int = 300) -> list[PanelRow]:
    return _history([100.0 * (1.003**i) for i in range(n)])


def _falling(n: int = 300) -> list[PanelRow]:
    return _history([100.0 * (0.997**i) for i in range(n)])


# --- insufficient history must yield None, never a smaller number ---


def _value(feature, history) -> float:  # type: ignore[no-untyped-def]
    """Assert a feature produced a number, and hand it back typed."""
    result = feature(history)
    assert result is not None, f"{feature.name} returned None on ample history"
    return float(result)


@pytest.mark.parametrize("feature", LIBRARY, ids=lambda f: f.name)
def test_a_feature_with_too_little_history_returns_none(feature) -> None:  # type: ignore[no-untyped-def]
    """A 12-month momentum on 5 days is not a small momentum, it is a
    different quantity. Letting it through would fill the early part of every
    backtest with something that does not mean what its name says.

    Each feature is given one row fewer than it declares it needs, rather than
    a fixed short history - `small_size` legitimately needs only one day, and
    a blanket assertion would have demanded it be broken.
    """
    if feature.min_history <= 1:
        pytest.skip(f"{feature.name} needs no history")
    short = _history([100.0 + i for i in range(feature.min_history - 1)])
    assert feature(short) is None


@pytest.mark.parametrize("feature", LIBRARY, ids=lambda f: f.name)
def test_every_feature_produces_a_number_on_ample_history(feature) -> None:  # type: ignore[no-untyped-def]
    value = feature(_rising())
    assert value is None or isinstance(value, float)


@pytest.mark.parametrize("feature", LIBRARY, ids=lambda f: f.name)
def test_no_feature_mutates_the_history_it_is_given(feature) -> None:  # type: ignore[no-untyped-def]
    """Purity is the contract the lookahead firewall relies on."""
    history = _rising()
    before = [(r.day, r.close) for r in history]
    feature(history)
    assert [(r.day, r.close) for r in history] == before


# --- signs: higher must mean better for every feature ---


def test_momentum_is_higher_for_a_riser_than_a_faller() -> None:
    assert _value(BY_NAME["momentum_12_1"], _rising()) > _value(
        BY_NAME["momentum_12_1"], _falling()
    )


def test_reversal_is_higher_for_a_recent_faller() -> None:
    """Negated, so a stock that just fell scores high — the direction the
    signal actually predicts."""
    assert _value(BY_NAME["reversal_1m"], _falling()) > _value(BY_NAME["reversal_1m"], _rising())


def test_low_volatility_is_higher_for_the_calmer_series() -> None:
    calm = _history([100.0 + (i % 2) * 0.1 for i in range(200)])
    wild = _history([100.0 * (1.15 if i % 2 else 0.87) for i in range(200)])
    assert _value(BY_NAME["low_volatility"], calm) > _value(BY_NAME["low_volatility"], wild)


def test_max_drawdown_is_higher_for_the_series_that_never_fell() -> None:
    assert _value(BY_NAME["max_drawdown"], _rising()) > _value(BY_NAME["max_drawdown"], _falling())


def test_liquidity_is_higher_for_the_more_traded_name() -> None:
    thin = _history([100.0] * 200, turnover=1000.0)
    thick = _history([100.0] * 200, turnover=10_000_000.0)
    assert _value(BY_NAME["turnover_liquidity"], thick) > _value(
        BY_NAME["turnover_liquidity"], thin
    )


def test_amihud_is_higher_for_the_name_that_moves_less_per_rupee_traded() -> None:
    deep = _history([100.0 * (1.0005**i) for i in range(200)], turnover=10_000_000.0)
    shallow = _history([100.0 * (1.0005**i) for i in range(200)], turnover=1000.0)
    assert _value(BY_NAME["illiquidity_amihud"], deep) > _value(
        BY_NAME["illiquidity_amihud"], shallow
    )


def test_price_to_52w_high_is_at_one_for_a_series_at_its_peak() -> None:
    assert _value(BY_NAME["price_to_52w_high"], _rising()) == pytest.approx(1.0)


def test_price_to_52w_high_is_below_one_after_a_fall() -> None:
    assert _value(BY_NAME["price_to_52w_high"], _falling()) < 1.0


def test_volume_trend_is_above_one_when_recent_volume_is_elevated() -> None:
    history = _history([100.0] * 100)
    spiked = history[:-5] + [
        PanelRow(
            day=r.day, symbol=r.symbol, close=r.close, volume=r.volume * 10, turnover=r.turnover
        )
        for r in history[-5:]
    ]
    assert _value(BY_NAME["volume_trend"], spiked) > 1.5


# --- the library itself ---


def test_the_library_has_ten_features_as_the_build_plan_requires() -> None:
    assert len(LIBRARY) == 10


def test_feature_names_are_unique() -> None:
    assert len({f.name for f in LIBRARY}) == len(LIBRARY)


def test_every_feature_documents_itself() -> None:
    for feature in LIBRARY:
        assert feature.description
        assert feature.fn.__doc__


# --- the trial counter is append-only ---


def test_a_trial_is_recorded_and_counted(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    trial = trials.Trial(
        logged_at=trials.now_iso(),
        feature="momentum_12_1",
        horizon_days=21,
        step_days=5,
        panel_start="2023-01-02",
        panel_end="2026-08-17",
        n_periods=124,
        mean_ic=0.05,
        t_stat=5.4,
    )
    assert trials.append(trial, path) == 1
    assert trials.append(trial, path) == 2


def test_the_log_only_ever_grows(tmp_path: Path) -> None:
    """CLAUDE.md: never bypass it, never reset it. Evaluating the same feature
    twice must count twice - that is the entire point of a trial counter, and
    deduplicating would understate the denominator of any later
    multiple-testing correction."""
    path = tmp_path / "trials.jsonl"
    trial = trials.Trial(
        logged_at=trials.now_iso(),
        feature="same",
        horizon_days=21,
        step_days=5,
        panel_start="a",
        panel_end="b",
        n_periods=1,
        mean_ic=0.0,
        t_stat=0.0,
    )
    for expected in (1, 2, 3):
        assert trials.append(trial, path) == expected
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 3


def test_counting_a_missing_log_is_zero_not_an_error(tmp_path: Path) -> None:
    assert trials.count(tmp_path / "absent.jsonl") == 0
