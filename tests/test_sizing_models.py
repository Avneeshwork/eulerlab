"""Declared sizing (ADR-121): equal by default, the strategy's own weights when
it says so, or a model; caps apply after."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from eulerlab.backtest.published import BUILDERS
from eulerlab.backtest.strategy import MarketView, Strategy, decide
from eulerlab.deploy import sizing_models as sm
from eulerlab.deploy.sizing import max_weight
from eulerlab.features.panel import PanelRow


def _view(vols: dict[str, float], days: int = 140, seed: int = 7) -> MarketView:
    """Random-walk closes with a chosen daily volatility per symbol."""
    rng = np.random.default_rng(seed)
    start = date(2025, 1, 1)
    history: dict[str, list[PanelRow]] = {}
    for symbol, vol in vols.items():
        price, rows = 100.0, []
        for i in range(days):
            price *= 1.0 + float(rng.normal(0.0, vol))
            rows.append(
                PanelRow(
                    day=start + timedelta(days=i),
                    symbol=symbol,
                    close=price,
                    volume=1e5,
                    turnover=1e7,
                    isin=f"INE{symbol}",
                )
            )
        history[symbol] = rows
    return MarketView(as_of=start + timedelta(days=days - 1), history=history)


VOLS = {"AAA": 0.01, "BBB": 0.02, "CCC": 0.03, "DDD": 0.015, "EEE": 0.025}


def test_equal_splits_gross_and_keeps_order() -> None:
    out = sm.size_book({"B": 0.5, "A": 0.3, "C": 0.2}, None, "equal")
    assert list(out) == ["B", "A", "C"]
    assert all(math.isclose(w, 1 / 3) for w in out.values())


def test_equal_keeps_idle_cash_of_a_slot_strategy() -> None:
    # Four signals in a 10-slot strategy: 10% each, 60% stays in cash.
    out = sm.size_book(dict.fromkeys("ABCD", 0.1), None, "equal")
    assert out == dict.fromkeys("ABCD", 0.1)


def test_equal_weights_come_back_untouched() -> None:
    weights = dict.fromkeys(["A", "B", "C"], 1.0 / 3)
    out = sm.size_book(weights, None, "equal")
    assert out == weights  # byte-identical: stored equal-weight results do not move


def test_strategy_rule_passes_weights_through() -> None:
    weights = {"A": 0.7, "B": 0.2, "C": 0.1}
    assert sm.size_book(weights, None, "strategy") == weights


def test_unknown_rule_is_refused() -> None:
    with pytest.raises(ValueError):
        sm.size_book({"A": 1.0}, None, "kelly")

    class Typo(Strategy):
        sizing = "inverse-vol"

        def target_weights(self, view: MarketView) -> dict[str, float]:
            return {}

    with pytest.raises(ValueError):
        sm.rule_of(Typo())


def test_inverse_vol_puts_less_on_the_volatile_name() -> None:
    view = _view(VOLS)
    out = sm.size_book(dict.fromkeys(VOLS, 0.2), view, "inverse_vol")
    assert math.isclose(sum(out.values()), 1.0)
    assert out["AAA"] > out["DDD"] > out["BBB"] > out["EEE"] > out["CCC"]


@pytest.mark.parametrize("rule", ["hrp", "min_variance"])
def test_risk_models_are_long_only_full_and_capped(rule: str) -> None:
    view = _view(VOLS)
    out = sm.size_book(dict.fromkeys(VOLS, 0.2), view, rule)
    assert math.isclose(sum(out.values()), 1.0, rel_tol=1e-9)
    assert all(w >= 0 for w in out.values())
    assert max(out.values()) <= max_weight(5) + 1e-9
    assert out["AAA"] > out["CCC"]  # the calm name gets more than the wild one


def test_models_keep_the_strategys_gross() -> None:
    view = _view(VOLS)
    out = sm.size_book(dict.fromkeys(VOLS, 0.1), view, "inverse_vol")
    assert math.isclose(sum(out.values()), 0.5)


def test_short_history_falls_back_to_equal() -> None:
    view = _view(VOLS, days=30)
    out = sm.size_book({"AAA": 0.5, "CCC": 0.3, "EEE": 0.2}, view, "min_variance")
    assert all(math.isclose(w, 1 / 3) for w in out.values())


def test_ledoit_wolf_is_between_sample_and_target() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.02, (126, 8))
    shrunk = sm.ledoit_wolf(returns)
    assert np.allclose(shrunk, shrunk.T)
    assert np.all(np.linalg.eigvalsh(shrunk) > 0)
    centred = returns - returns.mean(axis=0)
    assert np.allclose(np.diag(shrunk), np.diag(centred.T @ centred / 126))


def test_min_variance_matches_the_two_asset_formula() -> None:
    cov = np.array([[0.04, 0.0], [0.0, 0.01]])
    w = sm.min_variance(cov, cap=1.0)
    assert np.allclose(w, [0.2, 0.8], atol=1e-6)


def test_models_are_deterministic() -> None:
    view = _view(VOLS)
    for rule in sm.MODELS:
        a = sm.size_book(dict.fromkeys(VOLS, 0.2), view, rule)
        b = sm.size_book(dict.fromkeys(VOLS, 0.2), view, rule)
        assert a == b


def test_fit_ranks_a_modelled_book_by_order() -> None:
    class Modelled(Strategy):
        sizing = "inverse_vol"

        def target_weights(self, view: MarketView) -> dict[str, float]:
            return {}

    assert sm.fit_by_order(Modelled())


def test_decide_applies_the_declared_rule() -> None:
    class Unequal(Strategy):
        def target_weights(self, view: MarketView) -> dict[str, float]:
            return {"AAA": 0.6, "BBB": 0.3, "CCC": 0.1, "DDD": -0.2}

    view = _view(VOLS)
    longs, refused = decide(Unequal(), view)
    assert refused == ["DDD"]
    assert all(math.isclose(w, 1 / 3) for w in longs.values())
    own = Unequal()
    own.sizing = "strategy"
    assert decide(own, view)[0] == {"AAA": 0.6, "BBB": 0.3, "CCC": 0.1}


OWN_WEIGHTS = {
    "nse_github_stocks_on_the_move",
    "india_bab_low_beta",
    "nse_github_faber_taa_etf",
    "india_volatility_target_nifty",
}


def test_every_deployable_strategy_declares_a_valid_rule() -> None:
    for strategy_id, build in BUILDERS.items():
        strategy = build()
        rule = sm.rule_of(strategy)
        expected = "strategy" if strategy_id in OWN_WEIGHTS else "equal"
        assert rule == expected, strategy_id
