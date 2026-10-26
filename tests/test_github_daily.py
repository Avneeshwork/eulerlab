"""Research 113: five daily GitHub rules (`backtest/github_daily.py`)."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.backtest import github_daily as gd
from eulerlab.backtest.strategy import MarketView
from eulerlab.features.panel import PanelRow


def _rows(
    closes: list[float], *, symbol: str = "X", ranges: list[tuple[float, float]] | None = None
) -> list[PanelRow]:
    start = date(2020, 1, 1)
    out = []
    for i, close in enumerate(closes):
        high, low = ranges[i] if ranges else (close, close)
        out.append(
            PanelRow(
                day=start + timedelta(days=i),
                symbol=symbol,
                close=close,
                volume=1.0,
                turnover=1.0,
                open=close,
                high=high,
                low=low,
            )
        )
    return out


def test_in_trade_enters_then_leaves() -> None:
    enter = {2, 7}
    leave = {5}
    assert gd.in_trade(10, enter.__contains__, leave.__contains__, start=0) == 7
    assert gd.in_trade(6, enter.__contains__, leave.__contains__, start=0) is None
    assert gd.in_trade(5, enter.__contains__, leave.__contains__, start=0) == 2


def test_prior_extreme_uses_only_bars_before() -> None:
    values = [1.0, 5.0, 2.0, 3.0, 4.0, 0.5]
    assert gd.prior_extreme(values, 2, highest=True) == [None, None, 5.0, 5.0, 3.0, 4.0]
    assert gd.prior_extreme(values, 2, highest=False) == [None, None, 1.0, 2.0, 2.0, 3.0]


def test_ibs_buys_a_close_near_the_low_and_sells_one_near_the_high() -> None:
    ranges = [(10.0, 9.0)] * 3
    near_low = _rows([9.1, 9.5, 9.5], ranges=ranges)  # IBS 0.1, then 0.5
    assert gd.ibs_rule(near_low) is not None
    sold = _rows([9.1, 9.9], ranges=ranges[:2])  # IBS 0.1, then 0.9
    assert gd.ibs_rule(sold) is None


def test_trend_template_wants_a_rising_stock_near_its_high() -> None:
    rising = [100.0 * 1.003**i for i in range(300)]
    assert gd.trend_template(rising)
    falling = list(reversed(rising))
    assert not gd.trend_template(falling)


def test_dual_momentum_falls_back_to_the_better_safe_asset() -> None:
    n = 140
    down = [100.0 * 0.999**i for i in range(n)]
    gold = [100.0 * 1.002**i for i in range(n)]
    flat = [1000.0] * n
    view = MarketView(
        as_of=date(2020, 1, 1) + timedelta(days=n - 1),
        history={
            "NIFTYBEES": _rows(down, symbol="NIFTYBEES"),
            "JUNIORBEES": _rows(down, symbol="JUNIORBEES"),
            "GOLDBEES": _rows(gold, symbol="GOLDBEES"),
            "LIQUIDBEES": _rows(flat, symbol="LIQUIDBEES"),
        },
    )
    assert gd.DualMomentum("x").target_weights(view) == {"GOLDBEES": 1.0}
    rising = MarketView(
        as_of=view.as_of,
        history={
            **view.history,
            "JUNIORBEES": _rows([100.0 * 1.003**i for i in range(n)], symbol="JUNIORBEES"),
        },
    )
    assert gd.DualMomentum("x").target_weights(rising) == {"JUNIORBEES": 1.0}


def test_all_five_are_registered_and_deployable() -> None:
    from eulerlab.backtest.published import BUILDERS
    from eulerlab.deploy.runner import paper_blocker
    from eulerlab.strategies import REGISTRY

    for spec in gd.STRATEGIES:
        assert spec.id in BUILDERS and REGISTRY[spec.id].source.startswith("[GitHub]")
        assert paper_blocker(spec.id) == ""


def test_a_cross_enters_and_the_cross_back_leaves() -> None:
    fast: list[float | None] = [None, 1.0, 3.0, 3.0, 1.0]
    slow: list[float | None] = [None, 2.0, 2.0, 2.0, 2.0]
    assert gd.crossing_rule(fast, slow, 4) == 1, "entered one bar ago"
    assert gd.crossing_rule(fast, slow, 5) is None
    assert gd.crossing_rule([3.0, 3.0], [2.0, 2.0], 2) is None, "above without a cross is not in"


def test_supertrend_turns_up_in_a_rise_and_down_in_a_fall() -> None:
    up = [100.0 * 1.01**i for i in range(60)]
    rising = _rows(up, ranges=[(c * 1.005, c * 0.995) for c in up])
    assert gd.supertrend_rule(rising) is not None
    down = list(reversed(up))
    falling = _rows(down, ranges=[(c * 1.005, c * 0.995) for c in down])
    assert gd.supertrend_rule(falling) is None


def test_faber_puts_a_sleeve_below_its_average_in_cash() -> None:
    n = 10 * 21 + 5  # ten 21-session months, and a few days over
    rising = [100.0 * 1.001**i for i in range(n)]
    falling = list(reversed(rising))
    view = MarketView(
        as_of=date(2020, 1, 1) + timedelta(days=n - 1),
        history={
            "NIFTYBEES": _rows(rising, symbol="NIFTYBEES"),
            "JUNIORBEES": _rows(falling, symbol="JUNIORBEES"),
            "GOLDBEES": _rows(rising, symbol="GOLDBEES"),
            "LIQUIDBEES": _rows([1000.0] * n, symbol="LIQUIDBEES"),
        },
    )
    weights = gd.FaberTAA("x").target_weights(view)
    assert weights == {"NIFTYBEES": 0.25, "GOLDBEES": 0.25, "LIQUIDBEES": 0.5}, (
        "MON100 absent: cash"
    )


def test_more_names_than_slots_keeps_the_longest_held_at_fixed_weights() -> None:
    """2026-10-18: an equal share of everything in a trade re-sized every
    position daily as the count moved (122,004 golden-cross fills)."""
    ages = {"A": 5, "B": 30, "C": 0, "D": 30}
    view = MarketView(
        as_of=date(2020, 1, 1),
        history={s: _rows([100.0], symbol=s) for s in ages},
    )
    strategy = gd.PositionRule(
        "x", lambda rows: ages[rows[-1].symbol], lookback=1, slots=2, instruments=tuple(ages)
    )
    assert strategy.target_weights(view) == {"B": 0.5, "D": 0.5}
