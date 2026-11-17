"""The robustness battery before the gate (#158, ADR-211), on made-up markets."""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.research import experiments, lang
from eulerlab.validation import robust_battery as rb
from test_research_autopilot import _data
from test_research_bench import _fast, _panel, folder  # noqa: F401  (fixture)

FADE = lang.Spec(shape="event", kind="intraday", side="short", when="ge(gap, 0.02)", score="gap")


def _halves(sessions: list[date]) -> dict[str, dict[date, str]]:
    mid = sessions[len(sessions) // 2]
    return {"first or second half": {d: "first" if d < mid else "second" for d in sessions}}


def test_every_number_moves_either_way_and_bad_moves_are_dropped() -> None:
    spec = lang.Spec(
        shape="event",
        kind="swing",
        hold=10,
        when="ge(ts_mean(delay(ret(1), 1), 20), 0.01)",
        score="delay(ret(5), 1)",
    )
    moved = dict(rb.neighbours(spec))
    assert {"when: 0.01 -> 0.008", "when: 0.01 -> 0.012", "hold 10 -> 8", "hold 10 -> 12"} <= set(
        moved
    )
    assert {"when: ts_mean 20 -> 16", "when: ts_mean 20 -> 24", "score: ret 5 -> 4"} <= set(moved)
    assert spec.fingerprint() not in {s.fingerprint() for s in moved.values()}
    always = lang.Spec(shape="event", kind="intraday", score="gap")
    assert rb.neighbours(always) == []  # `when: 1` is not a number to move


def test_a_real_fade_passes_the_battery_and_every_run_is_counted(folder: Path) -> None:  # noqa: F811
    data = _panel(fade=True)
    found = rb.run(FADE, _fast(data), labels=_halves(data.sessions))
    by = {t.name: t for t in found.tests}
    assert found.sharpe is not None and found.sharpe > 0
    assert by["neighbours"].passed is True
    assert by["halves"].passed is True
    assert by["placebos"].passed is True, by["placebos"].detail
    assert by["regimes"].passed is True
    assert found.passed
    rows = experiments.rows(purpose="robust")
    tests = {r["metrics"]["test"] for r in rows}
    assert tests == {"neighbour", "half", "placebo"}
    assert sum(r["metrics"]["test"] == "half" for r in rows) == rb.HALVES
    assert all(r["metrics"]["of"] == FADE.fingerprint() for r in rows)


def test_the_same_rule_gets_the_same_battery(folder: Path) -> None:  # noqa: F811
    data = _panel(fade=True)
    labels = _halves(data.sessions)
    one = rb.run(FADE, _fast(data), labels=labels, record=False)
    two = rb.run(FADE, _fast(data), labels=labels, record=False)
    assert one.as_dict() == two.as_dict()


def test_a_rule_whose_timing_does_not_matter_fails_the_placebo(folder: Path) -> None:  # noqa: F811
    rng = random.Random(3)
    closes = {
        f"S{k:02d}": [100.0 * 1.004**i * (1 + rng.gauss(0, 0.002)) for i in range(160)]
        for k in range(30)
    }
    data = _data(closes)
    drift = lang.Spec(shape="event", kind="swing", hold=5, when="1", score="delay(ret(5), 1)")
    found = rb.run(drift, _fast(data), labels={}, record=False)
    by = {t.name: t for t in found.tests}
    assert by["placebos"].passed is False, by["placebos"].detail
    assert not found.passed


def test_profit_in_one_state_only_fails_the_regimes() -> None:
    sessions = [date(2022, 1, 3) + timedelta(days=i) for i in range(200)]
    daily = {d: (0.01 if i < 100 else -0.001) for i, d in enumerate(sessions)}
    labels = _halves(sessions)
    test = rb._regime_test(daily, labels)
    assert test.passed is False and "100%" in test.detail
    even = dict.fromkeys(sessions, 0.01)
    assert rb._regime_test(even, labels).passed is True


def test_regimes_read_the_day_before_and_need_two_states() -> None:
    sessions = [date(2019, 1, 1) + timedelta(days=i) for i in range(400)]
    nifty = {d: 100.0 + i for i, d in enumerate(sessions)}
    vix = {d: float(10 + i % 30) for i, d in enumerate(sessions)}
    labels = rb.regime_labels(sessions, nifty, vix)
    assert set(labels["Nifty vs 200-session mean"].values()) == {"above"}
    assert sessions[0] not in labels["India VIX tercile"]  # no prior close yet
    assert set(labels["India VIX tercile"].values()) == {"low", "middle", "high"}
    assert (
        rb._regime_test(dict.fromkeys(sessions, 0.01), {"one": dict.fromkeys(sessions, "x")}).passed
        is None
    )


def test_a_rule_that_loses_on_its_own_stops_at_the_screen(folder: Path) -> None:  # noqa: F811
    data = _panel(fade=True)
    wrong = lang.Spec(
        shape="event", kind="intraday", side="long", when="ge(gap, 0.02)", score="gap"
    )
    found = rb.run(wrong, _fast(data), labels={}, record=False)
    assert [t.name for t in found.tests] == ["screen"] and not found.passed


@pytest.mark.parametrize("lag", [5, 60])
def test_a_placebo_enters_later_and_only_on_tradable_days(lag: int) -> None:
    data = _panel()
    first = data.sessions[0]
    shifted = rb._shift(data, [(first, "S00", -1, 0.0)], lag)
    assert shifted == [(data.sessions[lag], "S00", -1, 0.0)]
    assert rb._shift(data, [(data.sessions[-1], "S00", -1, 0.0)], lag) == []
    assert _fast(data).screen(FADE, [])["count"] == 0  # the entries given replace the rule's


# --- the DP charge on a screen's delivery sells (#153) -----------------------------------


def test_a_swing_screen_pays_dp_on_each_sell_and_an_intraday_one_does_not() -> None:
    from eulerlab.costs import router
    from eulerlab.intraday import rule_engine as engine
    from eulerlab.strategies.studies import daily_more as dm

    data = _panel(fade=True)
    fast = _fast(data)
    swing = lang.Spec(shape="event", kind="swing", hold=5, when="ge(gap, 0.02)", score="gap")
    with_dp = fast.screen(swing)
    swings = dm.swing_book(data, fast.events(swing), swing.hold)
    without = sum(s.costs_at()[1] for s in swings)  # outside a screen: no DP (paper books)
    with router.dp_charges():
        again = dm.swing_book(data, fast.events(swing), swing.hold)
        paid = sum(s.costs_at()[1] for s in again)
    assert paid - without == pytest.approx(router.DP_CHARGE_INR * len(swings))
    assert with_dp["count"] == len(swings)
    trades = dm.day_book(data, fast.events(FADE))
    assert trades and engine.Engine(data).screen(FADE) == engine.Engine(data).screen(FADE)
