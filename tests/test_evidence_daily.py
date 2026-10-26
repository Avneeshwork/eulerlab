"""Research 113 batch 3: published momentum and reversal refinements."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eulerlab.backtest import evidence_daily as ev
from eulerlab.features.panel import PanelRow


def _rows(closes: list[float]) -> list[PanelRow]:
    start = date(2015, 1, 1)
    return [
        PanelRow(day=start + timedelta(days=i), symbol="X", close=c, volume=1.0, turnover=1.0)
        for i, c in enumerate(closes)
    ]


def test_a_stock_that_is_only_the_market_has_no_residual() -> None:
    market = [0.01, -0.02, 0.03, 0.0, 0.01, -0.01, 0.02, 0.01, -0.03, 0.02, 0.0, 0.01]
    stock = [0.001 + 1.5 * m for m in market]
    found = ev.residuals(stock, market)
    assert found is not None and max(abs(r) for r in found) < 1e-12


def test_steady_gains_are_continuous_and_jumps_are_discrete() -> None:
    n = 300
    steady = _rows([100.0 * 1.002**i for i in range(n)])
    # Mostly small falls, a few large jumps: the same kind of 12-1 gain, discrete.
    jumpy, price = [], 100.0
    for i in range(n):
        price *= 1.08 if i % 25 == 0 else 0.998
        jumpy.append(price)
    continuous = ev.information_discreteness(steady)
    discrete = ev.information_discreteness(_rows(jumpy))
    assert continuous is not None and discrete is not None
    assert continuous == pytest.approx(-1.0) and discrete > 0


def test_monthly_returns_count_back_21_sessions() -> None:
    rows = _rows([100.0 * 1.01 ** (i // 21) for i in range(64)])
    found = ev.monthly_returns(rows, 3)
    assert found is not None and len(found) == 3
    assert ev.monthly_returns(rows, 4) is None


def test_each_is_registered_with_its_source_and_deployable() -> None:
    from eulerlab.deploy.runner import paper_blocker
    from eulerlab.strategies import REGISTRY

    for spec in ev.STRATEGIES:
        tag = "[GitHub]" if spec.id.startswith("nse_github_") else "[paper]"
        assert REGISTRY[spec.id].source.startswith(tag)
        assert paper_blocker(spec.id) == ""


def _volume_rows(turnovers: list[float]) -> list[PanelRow]:
    start = date(2015, 1, 1)
    return [
        PanelRow(day=start + timedelta(days=i), symbol="X", close=100.0, volume=1.0, turnover=t)
        for i, t in enumerate(turnovers)
    ]


def test_a_high_volume_week_beats_the_ten_before_it() -> None:
    quiet = [100.0] * 55
    assert ev.high_volume_week(_volume_rows([*quiet, *[300.0] * 5]), 0)
    assert not ev.high_volume_week(_volume_rows([*quiet, *[100.0] * 5]), 0)
    assert ev.high_volume_week(_volume_rows([*quiet, *[300.0] * 5, *[100.0] * 5]), 1), "a week back"


def test_ma_distance_rises_above_one_in_a_rally() -> None:
    rising = _rows([100.0 * 1.002**i for i in range(220)])
    flat = _rows([100.0] * 220)
    distance = ev.ma_distance(rising)
    assert distance is not None and distance > 1.0
    assert ev.ma_distance(flat) == pytest.approx(1.0)


def test_clenow_scores_a_smooth_rise_and_drops_a_gap() -> None:
    smooth = _rows([100.0 * 1.003**i for i in range(140)])
    score = ev.clenow_score(smooth)
    assert score is not None and score > 0
    gapped = [100.0 * 1.003**i for i in range(140)]
    gapped[120] *= 1.2  # a 20% day inside the window
    assert ev.clenow_score(_rows(gapped)) is None
    falling = _rows([100.0 * 0.997**i for i in range(140)])
    assert ev.clenow_score(falling) is None, "under its 100-day average"


def test_dividend_yield_counts_the_last_year(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _rows([100.0] * 400)
    today = rows[-1].day
    monkeypatch.setattr(
        ev,
        "dividends",
        lambda: {"X": ((today - timedelta(days=400), 9.0), (today - timedelta(days=100), 2.0))},
    )
    assert ev.dividend_yield("X", rows) == pytest.approx(0.02)


def test_percentiles_run_from_zero_to_one() -> None:
    assert ev._percentiles({"a": 3.0, "b": 1.0, "c": 2.0}) == {"b": 0.0, "c": 0.5, "a": 1.0}


def test_mansfield_rs_and_stage_two() -> None:
    n = 300
    stock = _rows([100.0 * 1.002**i for i in range(n)])
    market = {r.day: 100.0 * 1.001**i for i, r in enumerate(stock)}
    rs = ev.mansfield_rs(stock, market)
    assert rs is not None and rs == pytest.approx((1.002 / 1.001) ** 252 - 1, rel=1e-6)
    assert ev.stage_two(stock)
    assert not ev.stage_two(_rows([100.0 * 0.999**i for i in range(n)]))


def test_halloween_switches_by_season() -> None:
    from eulerlab.backtest.strategy import MarketView

    strategy = ev.Halloween("x")
    assert strategy.target_weights(MarketView(as_of=date(2024, 12, 2), history={})) == {
        "NIFTYBEES": 1.0
    }
    assert strategy.target_weights(MarketView(as_of=date(2024, 6, 3), history={})) == {
        "LIQUIDBEES": 1.0
    }


def test_volatility_target_cuts_exposure_when_the_month_is_wild() -> None:
    from eulerlab.backtest.strategy import MarketView

    closes = [100.0]
    for i in range(1, 800):
        move = 0.05 if i > 780 and i % 2 else (-0.05 if i > 780 else (0.002 if i % 2 else -0.002))
        closes.append(closes[-1] * (1 + move))
    rows = [
        PanelRow(
            day=date(2016, 1, 1) + timedelta(days=i),
            symbol="NIFTYBEES",
            close=c,
            volume=1.0,
            turnover=1.0,
        )
        for i, c in enumerate(closes)
    ]
    found = ev.VolatilityTarget("x").target_weights(
        MarketView(as_of=rows[-1].day, history={"NIFTYBEES": rows})
    )
    assert 0 < found["NIFTYBEES"] < 0.5 and found["LIQUIDBEES"] == pytest.approx(
        1 - found["NIFTYBEES"]
    )
