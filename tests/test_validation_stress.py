"""Stress tests: not "is this significant" but "when does this break"."""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.validation import stress

START = date(2018, 1, 1)


def _panel(n_symbols: int = 20, n_days: int = 1200, drift: float = 0.0006) -> list[PanelRow]:
    rows: list[PanelRow] = []
    for s in range(n_symbols):
        price = 100.0
        for d in range(n_days):
            price *= 1.0 + drift
            rows.append(
                PanelRow(
                    day=START + timedelta(days=d),
                    symbol=f"SYM{s:02d}",
                    close=price,
                    volume=1000.0,
                    turnover=1e9,
                    isin=f"TEST{s:06d}",
                )
            )
    return rows


class _HoldFive(Strategy):
    name = "hold_five"
    lookback = 5

    def target_weights(self, view: MarketView) -> dict[str, float]:
        chosen = view.symbols()[:5]
        return dict.fromkeys(chosen, 0.2)


def test_higher_costs_never_improve_a_result() -> None:
    """The multiplier must actually reach the charges. The first version
    scaled only brokerage — which defaults to zero on delivery — so 'costs x5'
    barely moved anything and reported a robustness that was not real."""
    rows = _panel()
    results = stress.cost_multiple(rows, _HoldFive(), multiples=(1.0, 2.0, 5.0), rebalance=60)
    assert results
    for r in results:
        assert r.stressed <= r.base + 1e-9


def test_costs_bite_harder_as_the_multiple_rises() -> None:
    rows = _panel()
    results = stress.cost_multiple(rows, _HoldFive(), multiples=(1.0, 2.0, 5.0), rebalance=60)
    by_name = {r.name: r.stressed for r in results}
    assert by_name["costs x5"] <= by_name["costs x2"]


def test_dropping_the_best_names_is_reported() -> None:
    """Concentration is invisible in a Sharpe ratio and fatal to the
    conclusion: if a result rests on five names out of thousands, nothing
    about it generalises."""
    rows = _panel()
    result = stress.drop_best_contributors(rows, _HoldFive(), drop=2, rebalance=60)
    assert "removed" in result.detail


def test_the_regime_split_covers_both_halves() -> None:
    rows = _panel()
    results = stress.by_regime(rows, _HoldFive(), rebalance=60)
    names = {r.name for r in results}
    assert "regime: first half" in names
    assert "regime: second half" in names


def test_a_too_short_regime_half_is_skipped_rather_than_reported() -> None:
    """A Sharpe from 200 days is not comparable to one from 1,200."""
    assert stress.by_regime(_panel(n_days=300), _HoldFive(), rebalance=60) == []


def test_a_negative_stressed_result_is_flagged_as_failing() -> None:
    r = stress.StressResult(name="x", detail="", base=1.0, stressed=-0.2)
    assert not r.survives
    assert "FAIL" in stress.render([r])


def test_retained_fraction_is_reported() -> None:
    r = stress.StressResult(name="x", detail="", base=2.0, stressed=1.0)
    assert r.retained == 0.5


def test_a_zero_base_does_not_divide_by_zero() -> None:
    assert stress.StressResult(name="x", detail="", base=0.0, stressed=1.0).retained == 0.0


def test_the_cost_multiplier_reaches_the_engine() -> None:
    """Directly, rather than only through the stress wrapper."""
    from eulerlab.backtest import event_driven

    rows = _panel()
    base = event_driven.run(rows, _HoldFive(), rebalance_every=60)
    doubled = event_driven.run(rows, _HoldFive(), rebalance_every=60, cost_multiplier=2.0)
    assert doubled.total_cost > base.total_cost * 1.9
