"""Persisted backtest results, and the bias that comes free with them.

The operator asked for a strategy's best backtest result to be saved as its
result. That is a reasonable thing to want and it is also, precisely, max-of-N
— the estimator this whole project exists to correct for. These tests pin the
compromise: the best result is stored and reported, and it is impossible to
obtain without also obtaining how many runs it beat.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eulerlab import results as rs
from eulerlab import workspace as ws


@pytest.fixture()
def space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ws.Workspace:
    monkeypatch.setattr(ws, "ROOT", tmp_path / "workspaces")
    return ws.Workspace(id="tenant-a").ensure()


def _run(
    sharpe: float, *, window: int = 800, fills: int = 100, tier: str = "A", **params: object
) -> rs.Run:
    return rs.Run(
        strategy_id="demo",
        sharpe=sharpe,
        total_return=0.2,
        max_drawdown=-0.1,
        fills=fills,
        days=window,
        tier=tier,
        window_days=window,
        data_version="v1",
        params=dict(params),
    )


# --- the headline number ---------------------------------------------------


def test_the_best_result_is_what_gets_reported(space: ws.Workspace) -> None:
    for sharpe in (0.4, 2.19, 1.1):
        rs.record(space, _run(sharpe, window=int(500 + sharpe * 100)))
    top = rs.best(space, "demo")
    assert top is not None
    assert top.run.sharpe == 2.19


def test_the_best_cannot_be_obtained_without_its_denominator(space: ws.Workspace) -> None:
    """The compromise, enforced by the type rather than by discipline.

    A Sharpe of 2.19 means one thing as the only run and another as the highest
    of three. `Best` carries both, so a caller cannot take the figure and leave
    the count behind.
    """
    for sharpe, window in ((0.4, 500), (2.19, 800), (1.1, 1200)):
        rs.record(space, _run(sharpe, window=window))
    top = rs.best(space, "demo")
    assert top is not None
    assert top.runs == 3
    assert top.is_a_maximum is True


def test_a_single_run_is_a_measurement_not_a_maximum(space: ws.Workspace) -> None:
    rs.record(space, _run(1.4))
    top = rs.best(space, "demo")
    assert top is not None
    assert top.runs == 1
    assert top.is_a_maximum is False, "one run is a measurement; there was nothing to select from"


def test_the_caveat_appears_only_when_the_figure_is_a_maximum(space: ws.Workspace) -> None:
    rs.record(space, _run(1.4))
    assert "Best of" not in rs.summary(space, "demo")["caveat"]

    rs.record(space, _run(2.0, window=1200))
    caveat = rs.summary(space, "demo")["caveat"]
    assert "Best of 2 configurations" in caveat
    assert "luckiest draw" in caveat


# --- what counts as a distinct attempt -------------------------------------


def test_rerunning_an_identical_configuration_does_not_inflate_the_count(
    space: ws.Workspace,
) -> None:
    """Otherwise running the same backtest ten times would report ten
    configurations and make the bias correction stronger than the search
    justifies — punishing a re-run as though it were a new idea."""
    for _ in range(5):
        rs.record(space, _run(1.4))
    top = rs.best(space, "demo")
    assert top is not None
    assert top.runs == 1


def test_a_different_window_is_a_different_configuration(space: ws.Workspace) -> None:
    rs.record(space, _run(1.0, window=500))
    rs.record(space, _run(1.0, window=800))
    top = rs.best(space, "demo")
    assert top is not None
    assert top.runs == 2


def test_a_different_tier_is_a_different_configuration(space: ws.Workspace) -> None:
    """Tier A is a screen and Tier B is the engine. The same strategy on each is
    two results, not one recomputed."""
    rs.record(space, _run(1.0, tier="A"))
    rs.record(space, _run(1.0, tier="B"))
    top = rs.best(space, "demo")
    assert top is not None
    assert top.runs == 2


def test_a_later_run_supersedes_an_identical_earlier_one(space: ws.Workspace) -> None:
    rs.record(space, rs.Run(**{**_run(1.0).__dict__, "at": "2026-01-01T00:00:00+00:00"}))
    rs.record(space, rs.Run(**{**_run(1.9).__dict__, "at": "2026-06-01T00:00:00+00:00"}))
    top = rs.best(space, "demo")
    assert top is not None
    assert top.runs == 1
    assert top.run.sharpe == 1.9, "same configuration, so the later result replaces the earlier"


# --- what is not a result --------------------------------------------------


def test_a_run_that_never_traded_is_not_a_result(space: ws.Workspace) -> None:
    """Zero fills means the strategy held nothing all run — usually a window
    shorter than its lookback. Letting that win a maximum would be absurd and
    letting it lose one is equally wrong, so it is excluded outright."""
    rs.record(space, _run(0.0, fills=0))
    assert rs.best(space, "demo") is None
    assert rs.summary(space, "demo")["sharpe"] is None


def test_nothing_run_reports_none_never_zero(space: ws.Workspace) -> None:
    """Zero is a measurement meaning no edge; None means nobody looked."""
    assert rs.best(space, "never-run") is None
    assert rs.summary(space, "never-run") == {"sharpe": None, "runs": 0, "caveat": ""}


def test_unrecorded_search_is_counted_and_stated(space: ws.Workspace) -> None:
    """Screening spends no trial, so the noise bar does not know these runs
    happened. The library reports how much of its own evidence is invisible to
    the bar."""
    rs.record(space, _run(1.0, window=500))
    rs.record(space, _run(2.0, window=800))
    summary = rs.summary(space, "demo")
    assert summary["unrecorded"] == 2
    assert "noise bar does not know" in summary["caveat"]


# --- tenancy ---------------------------------------------------------------


def test_results_do_not_leak_between_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ws, "ROOT", tmp_path / "workspaces")
    a = ws.Workspace(id="tenant-a").ensure()
    b = ws.Workspace(id="tenant-b").ensure()

    rs.record(a, _run(2.19))
    assert rs.best(a, "demo") is not None
    assert rs.best(b, "demo") is None, "one tenant's evidence must not appear in another's"


def test_a_torn_final_line_does_not_lose_the_file(space: ws.Workspace) -> None:
    rs.record(space, _run(1.4))
    path = space.results / "demo.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"strategy_id": "de')
    top = rs.best(space, "demo")
    assert top is not None, "a crash mid-write must not discard the completed runs"
    assert top.runs == 1
