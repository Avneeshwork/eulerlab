"""Fitting a strategy's list to the money: cut from the bottom of the ranking."""

from __future__ import annotations

from eulerlab.deploy.sizing import fit_to_capital, ranked


def test_everything_affordable_is_unchanged() -> None:
    targets = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    out = fit_to_capital(targets, 100_000, lambda s: 100.0)
    assert out == targets


def test_the_lowest_ranked_names_are_cut_first() -> None:
    # Twenty names, best first, ₹1,000 a share, ₹6,000 to spend: a ₹300 slice
    # buys nothing, and six slices of ₹1,000 buy one share each.
    targets = {f"S{i:02d}": 0.05 for i in range(20)}
    out = fit_to_capital(targets, 6_000, lambda s: 1_000.0)
    assert list(out) == [f"S{i:02d}" for i in range(6)]
    assert abs(sum(out.values()) - 1.0) < 1e-12


def test_an_expensive_top_name_limits_how_many_are_kept() -> None:
    targets = {"TOP": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    prices = {"TOP": 30_000.0, "B": 10.0, "C": 10.0, "D": 10.0}
    # ₹60,000: four slices of ₹15,000 cannot buy TOP; two of ₹30,000 can.
    out = fit_to_capital(targets, 60_000, prices.get)
    assert list(out) == ["TOP", "B"]
    assert out["TOP"] == 0.5


def test_nothing_affordable_holds_nothing() -> None:
    assert fit_to_capital({"A": 1.0}, 500, lambda s: 1_000.0) == {}


def test_rank_is_weight_then_the_strategys_order() -> None:
    assert ranked({"Z": 0.1, "A": 0.3, "M": 0.1}) == ["A", "Z", "M"]
