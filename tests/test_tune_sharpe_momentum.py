"""The sweep's selection rule: a plateau beats a lone peak."""

from __future__ import annotations

from eulerlab.backtest.india_papers import YEAR, sharpe_momentum, sharpe_momentum_over
from eulerlab.research import tune_sharpe_momentum as tune


def test_grid_contains_the_paper_setting() -> None:
    assert tune.PAPER in tune.grid()
    assert len(tune.grid()) == 64


def test_paper_score_is_the_one_year_window() -> None:
    assert sharpe_momentum.__code__ is sharpe_momentum_over(YEAR).__code__


def test_neighbours_step_one_axis_at_a_time() -> None:
    corner = (63, 10, 10)
    assert sorted(tune._neighbours(corner)) == [(63, 10, 21), (63, 20, 10), (126, 10, 10)]
    assert len(tune._neighbours((126, 20, 21))) == 6


def test_a_lone_peak_loses_to_a_plateau() -> None:
    sharpes = dict.fromkeys(tune.grid(), 0.0)
    sharpes[(63, 10, 10)] = 3.0  # a spike with poor neighbours
    for p in [(189, 30, 42), *tune._neighbours((189, 30, 42))]:
        sharpes[p] = 1.0
    sharpes[(189, 30, 42)] = 1.2
    assert tune.choose(sharpes) == (189, 30, 42)


def test_describe_compounds_and_finds_the_drawdown() -> None:
    out = tune.describe([0.10, -0.50, 0.20])
    assert out["total_return"] == round(1.1 * 0.5 * 1.2 - 1, 4)
    assert out["max_drawdown"] == -0.5
