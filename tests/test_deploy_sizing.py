"""Fitting a strategy's list to the money: ranked, capped, and an unaffordable
name skipped rather than cutting everything below it (ADR-120)."""

from __future__ import annotations

from itertools import pairwise

import pytest

from eulerlab.deploy.sizing import capped, fit_to_capital, max_weight, ranked


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


def test_an_expensive_top_name_is_skipped_not_the_whole_list() -> None:
    # Before ADR-120 TOP kept the book to two names, TOP at 50%. Now TOP is
    # skipped and the three it would have crowded out are held.
    targets = {"TOP": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    prices = {"TOP": 30_000.0, "B": 10.0, "C": 10.0, "D": 10.0}
    out = fit_to_capital(targets, 60_000, prices.get)
    assert list(out) == ["B", "C", "D"]
    assert out["B"] == pytest.approx(1 / 3)


def test_one_expensive_share_cannot_become_the_book() -> None:
    # The 29 Oct 2026 Clenow paper book: ₹50,000, a ₹47,589 BOSCHLTD at the
    # top by weight, and cheap names below it. It used to hold BOSCHLTD alone.
    targets = {"BOSCHLTD": 0.10, **{f"S{i:02d}": 0.9 / 24 for i in range(24)}}
    prices = {"BOSCHLTD": 47_589.0, **{f"S{i:02d}": 500.0 for i in range(24)}}
    out = fit_to_capital(targets, 50_000, prices.get)
    assert "BOSCHLTD" not in out
    assert len(out) == 24
    assert max(out.values()) <= max_weight(24) + 1e-12


@pytest.mark.parametrize(("k", "cap"), [(1, 1.0), (5, 0.35), (10, 0.25), (20, 0.15)])
def test_the_operators_caps(k: int, cap: float) -> None:
    assert max_weight(k) == pytest.approx(cap)


def test_every_cap_leaves_a_full_book_possible_and_falls_with_size() -> None:
    caps = [max_weight(k) for k in range(1, 61)]
    assert all(c * k >= 1.0 - 1e-12 for k, c in enumerate(caps, start=1))
    assert all(a >= b for a, b in pairwise(caps))
    assert max_weight(25) == pytest.approx(0.12)


def test_a_concentrated_book_is_capped_and_the_excess_spread() -> None:
    # Ten names, one asking for 55%: capped at 25%, the other nine share the
    # rest in proportion to their own weights.
    targets = {"BIG": 0.55, **{f"S{i}": 0.05 for i in range(9)}}
    out = fit_to_capital(targets, 1_000_000, lambda s: 10.0)
    assert out["BIG"] == pytest.approx(0.25)
    assert out["S0"] == pytest.approx(0.75 / 9)
    assert sum(out.values()) == pytest.approx(1.0)


def test_capping_repeats_until_nobody_is_over() -> None:
    out = capped({"A": 0.5, "B": 0.3, "C": 0.1, "D": 0.05, "E": 0.05}, 0.35)
    assert out["A"] == pytest.approx(0.35)
    assert out["B"] == pytest.approx(0.35)
    assert sum(out.values()) == pytest.approx(1.0)
    assert out["C"] == pytest.approx(2 * out["D"])


def test_gross_exposure_is_kept() -> None:
    targets = {"A": 0.49, "B": 0.49}
    out = fit_to_capital(targets, 100_000, lambda s: 10.0)
    assert sum(out.values()) == pytest.approx(0.98)


def test_nothing_affordable_holds_nothing() -> None:
    assert fit_to_capital({"A": 1.0}, 500, lambda s: 1_000.0) == {}


def test_rank_is_weight_then_the_strategys_order() -> None:
    assert ranked({"Z": 0.1, "A": 0.3, "M": 0.1}) == ["A", "Z", "M"]


def test_a_strategy_whose_weights_are_sizes_is_ranked_by_its_order() -> None:
    # Clenow lists best trend first and weights by inverse volatility: the
    # calm third name has the largest weight but the weakest trend.
    targets = {"TREND1": 0.2, "TREND2": 0.2, "CALM": 0.6}
    assert ranked(targets, by_order=True) == ["TREND1", "TREND2", "CALM"]
    # ₹1,000 buys two ₹400 slices: by weight CALM goes first, by order it is cut.
    by_weight = fit_to_capital(targets, 1_000, lambda s: 400.0)
    by_order = fit_to_capital(targets, 1_000, lambda s: 400.0, by_order=True)
    assert "CALM" in by_weight
    assert list(by_order) == ["TREND1", "TREND2"]
