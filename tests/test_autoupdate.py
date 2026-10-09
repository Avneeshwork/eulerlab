"""The price panel and the paper books follow the data by themselves.

Operator, 2026-10-09: "price panel and paper trading should auto update on data
change". `deploy/autoupdate.py`, `daily_feed.DEPENDENTS`.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from eulerlab.deploy import autoupdate
from eulerlab.ingest import daily_feed, filelock


def test_a_cash_bhavcopy_update_pulls_in_the_panel_and_the_paper_books() -> None:
    wanted = daily_feed.with_dependents(["NSE end-of-day"])
    assert {"price panel", "paper books", "Nifty options"} <= wanted
    assert daily_feed.with_dependents(["price panel"]) == {"price panel", "paper books"}
    assert daily_feed.with_dependents([]) == set(), "empty still means every step"
    names = {n for n, _ in daily_feed.STEPS}
    for parent, children in daily_feed.DEPENDENTS.items():
        assert {parent, *children} <= names


def test_the_panel_is_not_rebuilt_when_nothing_newer_landed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eulerlab.features import panel

    monkeypatch.setattr(autoupdate, "landed_cash_day", lambda: "2026-10-08")
    monkeypatch.setattr(autoupdate, "panel_day", lambda: "2026-10-08")
    monkeypatch.setattr(panel, "build", lambda **k: pytest.fail("rebuilt for nothing"))
    assert autoupdate.update_panel() == (0, "2026-10-08")


def test_a_newer_landed_day_builds_the_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.features import panel

    days = iter(["2026-10-07", "2026-10-08"])
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(autoupdate, "landed_cash_day", lambda: "2026-10-08")
    monkeypatch.setattr(autoupdate, "panel_day", lambda: next(days))

    def build(**kwargs: Any) -> tuple[int, str]:
        calls.append(kwargs)
        return 1, ""

    monkeypatch.setattr(panel, "build", build)
    assert autoupdate.update_panel() == (1, "2026-10-08")
    assert calls == [{"start": "2015-01-01", "end": "2026-10-08"}]


def _books(monkeypatch: pytest.MonkeyPatch, states: dict[str, dict[str, Any]]) -> None:
    from eulerlab.deploy import deployments as store

    deps = [SimpleNamespace(id=i, status="active", mode="paper") for i in states]
    monkeypatch.setattr(store, "all_deployments", lambda: deps)
    monkeypatch.setattr(store, "read_state", lambda d: states[d.id])


def test_only_books_behind_the_panel_are_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    _books(
        monkeypatch,
        {
            "behind": {"traded_through": "2026-10-07"},
            "current": {"traded_through": "2026-10-08"},
            "waiting-seen": {"status": "waiting", "panel_through": "2026-10-08"},
            "waiting-new": {"status": "waiting", "panel_through": "2026-10-07"},
        },
    )
    assert sorted(autoupdate.books_behind("2026-10-08")) == ["behind", "waiting-new"]


def test_behind_books_are_run_together(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.deploy import runner

    _books(monkeypatch, {"a": {"traded_through": "2026-10-07"}, "b": {}})
    calls: list[Any] = []

    def run_all(only: Any = "") -> int:
        calls.append(only)
        return 0

    monkeypatch.setattr(runner, "run_all", run_all)
    assert autoupdate.update_paper("2026-10-08") == ["a", "b"]
    assert calls == [["a", "b"]], "one run, so the panel is read once"


def test_it_stands_aside_while_a_feed_run_holds_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(autoupdate, "update_panel", lambda: pytest.fail("raced the feed"))
    with filelock.exclusive("feed", wait=False):
        assert "feed lock" in autoupdate.catch_up().skipped


def test_a_failed_check_does_not_end_the_watcher(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stop = threading.Event()
    calls = 0

    def boom() -> autoupdate.CatchUp:
        nonlocal calls
        calls += 1
        if calls >= 2:
            stop.set()
        raise RuntimeError("B2 unreachable")

    monkeypatch.setattr(autoupdate, "catch_up", boom)
    autoupdate.watch(stop, interval=0.01)
    assert calls == 2, "it kept checking after the first failure"
    assert "B2 unreachable" in capsys.readouterr().out


def test_it_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EULERLAB_AUTOUPDATE", "0")
    assert autoupdate.enabled() is False
