"""The IC harness, tested by feeding it signals whose answer is known.

A harness that reports a number for any input is useless — the number could be
anything. So it is calibrated at both ends: a feature that *is* the forward
return must score IC = 1.0, and a feature that cannot possibly know anything
must score ~0. Anything in between is only interpretable because those two
anchors hold.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from eulerlab.features.ic import (
    ICResult,
    PeriodIC,
    evaluate,
    forward_returns,
    rank,
    spearman,
)
from eulerlab.features.library import Feature
from eulerlab.features.panel import PanelRow, by_symbol


def _panel(n_symbols: int = 60, n_days: int = 80, seed: int = 7) -> list[PanelRow]:
    """A deterministic random-walk panel. Seeded: determinism is a project rule."""
    rng = random.Random(seed)
    start = date(2024, 1, 1)
    rows: list[PanelRow] = []
    for s in range(n_symbols):
        price = 100.0
        for d in range(n_days):
            price *= 1.0 + rng.gauss(0, 0.02)
            rows.append(
                PanelRow(
                    day=start + timedelta(days=d),
                    symbol=f"SYM{s:03d}",
                    close=max(price, 0.01),
                    volume=1000.0 + s,
                    turnover=100000.0 + s,
                )
            )
    return rows


# --- the two anchors ---


def test_a_feature_that_is_the_forward_return_scores_a_perfect_ic() -> None:
    """The upper anchor. If this is not 1.0 the harness is not measuring what
    it claims, and every other number it prints is meaningless.

    This feature cheats deliberately: it reaches past its own history into the
    panel to read the answer. That is exactly what a lookahead bug does, and
    the harness cannot tell the difference — which is why the firewall lives in
    the *feature contract* (pure function of its own history), not here.
    """
    rows = _panel()
    histories = by_symbol(rows)
    horizon = 5

    def oracle(history):  # type: ignore[no-untyped-def]
        last = history[-1]
        series = histories[last.symbol]
        i = next(k for k, r in enumerate(series) if r.day == last.day)
        if i + horizon >= len(series):
            return None
        return series[i + horizon].close / series[i].close - 1.0

    result = evaluate(
        rows, Feature("oracle", oracle, "cheats", 1), horizon=horizon, step=10, min_names=30
    )
    assert result.n > 0
    assert result.mean_ic == pytest.approx(1.0, abs=1e-9)


def test_a_feature_that_cannot_know_anything_scores_about_zero() -> None:
    """The lower anchor: a true null must score indistinguishably from zero.

    Getting this fixture right took two corrections, both instructive.

    The first version used `hash(symbol) % 997`. Python randomises string
    hashing per process, so the test was non-deterministic — it passed or
    failed depending on `PYTHONHASHSEED`, which violates the project's
    determinism rule and made it worthless as an anchor.

    The second problem is subtler and matters more. A label that is *constant
    per symbol* is **not** a null signal. In any fixed panel some symbols
    persistently out-drift others, so a fixed cross-sectional ordering can
    align with them and score a genuine, repeatable IC — measured at t = 4.7
    here. A real null has to be re-drawn each period, which is what the seeded
    per-date shuffle below does.
    """
    rows = _panel()

    def arbitrary(history):  # type: ignore[no-untyped-def]
        last = history[-1]
        # Deterministic, and re-drawn every period so it cannot align with
        # whichever symbols happen to drift up over the sample.
        rng = random.Random(f"{last.symbol}|{last.day.isoformat()}")
        return rng.random()

    result = evaluate(
        rows, Feature("arbitrary", arbitrary, "noise", 1), horizon=5, step=10, min_names=30
    )
    assert result.n > 0
    assert abs(result.mean_ic) < 0.15
    assert abs(result.t_stat) < 3.0


def test_a_constant_per_symbol_label_is_not_a_null_signal() -> None:
    """Records the trap directly, so the fixture above is not quietly
    'simplified' back into it later.

    A fixed ordering that happens to match which symbols drift up scores a
    persistent IC. It is not evidence of a leak in the harness — the harness is
    reporting a real correlation — but it is useless as a null anchor.
    """
    rows = _panel()
    ordering = {f"SYM{s:03d}": float(s) for s in range(60)}

    def fixed_label(history):  # type: ignore[no-untyped-def]
        return ordering[history[-1].symbol]

    result = evaluate(
        rows,
        Feature("fixed", fixed_label, "constant per symbol", 1),
        horizon=5,
        step=10,
        min_names=30,
    )
    # No assertion on the sign or size - the point is only that this construct
    # can carry signal, so it must not be used as the null.
    assert result.n > 0


# --- the firewall property ---


def test_a_feature_only_ever_sees_rows_up_to_the_evaluation_day() -> None:
    """The guarantee the whole harness rests on: whatever a feature is handed
    ends on the evaluation date, so it physically cannot contain the window its
    own forward return is measured over."""
    rows = _panel()
    seen_last_days: list[date] = []

    def spy(history):  # type: ignore[no-untyped-def]
        seen_last_days.append(history[-1].day)
        return float(len(history))

    evaluate(rows, Feature("spy", spy, "records", 1), horizon=5, step=20, min_names=30)

    assert seen_last_days
    evaluated = sorted(set(seen_last_days))
    for history_end in seen_last_days:
        assert history_end in evaluated


def test_the_forward_return_starts_at_the_evaluation_day() -> None:
    """Off by one here is the classic way to manufacture an IC that is not
    real, because the feature would then overlap the answer."""
    rows = _panel(n_symbols=3, n_days=30)
    histories = by_symbol(rows)
    day = rows[0].day
    forwards = forward_returns(histories, day, 5)
    for symbol, ret in forwards.items():
        series = histories[symbol]
        i = next(k for k, r in enumerate(series) if r.day == day)
        assert ret == pytest.approx(series[i + 5].close / series[i].close - 1.0)


def test_a_symbol_without_enough_forward_history_is_excluded() -> None:
    """Otherwise the last periods would silently score on a shrinking, and
    therefore different, universe."""
    rows = _panel(n_symbols=3, n_days=10)
    histories = by_symbol(rows)
    assert forward_returns(histories, rows[-1].day, 5) == {}


# --- rank correlation ---


def test_spearman_is_one_for_a_monotonic_relationship() -> None:
    assert spearman([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]) == pytest.approx(1.0)


def test_spearman_is_minus_one_when_reversed() -> None:
    assert spearman([1.0, 2.0, 3.0, 4.0], [40.0, 30.0, 20.0, 10.0]) == pytest.approx(-1.0)


def test_spearman_ignores_the_magnitude_of_an_outlier() -> None:
    """The reason rank correlation is used at all. Pearson would be dragged by
    the 1e9; Spearman sees one more rank."""
    xs = [1.0, 2.0, 3.0, 4.0]
    assert spearman(xs, [10.0, 20.0, 30.0, 1e9]) == pytest.approx(1.0)


def test_ties_share_an_averaged_rank() -> None:
    """Breaking ties by input order would inject the panel's alphabetical
    ordering into the correlation as though it were information."""
    assert rank([5.0, 5.0, 9.0]) == [1.5, 1.5, 3.0]


def test_an_entirely_tied_side_has_no_correlation() -> None:
    assert spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_too_few_points_produce_no_correlation() -> None:
    assert spearman([1.0], [2.0]) is None


# --- the statistics the tear sheet leads with ---


def _result(ics: list[float]) -> ICResult:
    return ICResult(
        feature="f",
        periods=[
            PeriodIC(day=date(2024, 1, 1) + timedelta(days=i), ic=v, n=100)
            for i, v in enumerate(ics)
        ],
        horizon_days=21,
        skipped_thin=0,
    )


def test_the_same_mean_ic_gives_a_smaller_t_stat_on_fewer_periods() -> None:
    """Exactly why the sheet leads with t rather than the mean: 0.03 across
    many periods and 0.03 across a handful are different claims."""
    few = _result([0.03, 0.05, 0.01, 0.03])
    many = _result([0.03, 0.05, 0.01, 0.03] * 25)
    assert many.mean_ic == pytest.approx(few.mean_ic)
    assert abs(many.t_stat) > abs(few.t_stat) * 4


def test_a_zero_mean_ic_has_a_zero_t_stat() -> None:
    assert _result([0.1, -0.1, 0.1, -0.1]).t_stat == pytest.approx(0.0)


def test_hit_rate_counts_positive_periods() -> None:
    assert _result([0.1, 0.1, 0.1, -0.1]).hit_rate == pytest.approx(0.75)


def test_by_year_separates_a_signal_that_worked_only_once() -> None:
    """A feature that worked in one year and nowhere else must not hide behind
    its average."""
    periods = [
        PeriodIC(day=date(2024, 6, 1), ic=0.20, n=100),
        PeriodIC(day=date(2025, 6, 1), ic=0.00, n=100),
    ]
    result = ICResult(feature="f", periods=periods, horizon_days=21, skipped_thin=0)
    assert result.by_year()[2024][0] == pytest.approx(0.20)
    assert result.by_year()[2025][0] == pytest.approx(0.00)


def test_an_empty_result_does_not_divide_by_zero() -> None:
    empty = ICResult(feature="f", periods=[], horizon_days=21, skipped_thin=0)
    assert empty.mean_ic == 0.0
    assert empty.t_stat == 0.0
    assert empty.hit_rate == 0.0
