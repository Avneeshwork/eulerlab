"""On-call, reconciliation and the fund report (ADR-182)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab import fund_report, jobrun, oncall
from eulerlab.agents import jobs
from eulerlab.costs.schedule import Side
from eulerlab.deploy import deployments, runner
from eulerlab.risk.limits import loss_limits

NOW = datetime(2026, 11, 13, 11, tzinfo=UTC)
RULES = Path(__file__).parents[1] / "config" / "constitution.yaml"


@pytest.fixture
def desk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "constitution.yaml").write_text(RULES.read_text())
    llm = Path(__file__).parents[1] / "config" / "llm.yaml"
    (tmp_path / "config" / "llm.yaml").write_text(llm.read_text())
    monkeypatch.setenv("EULERLAB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(deployments, "ROOT", tmp_path / "data" / "deployments")
    monkeypatch.setattr(oncall, "_page", lambda text: None)
    return tmp_path


def test_a_planted_feed_failure_is_fixed_without_a_person(
    desk: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #148: the data agent's dead letter is re-run by on-call and settled."""
    ran: list[list[str]] = []

    def rerun(names: list[str]) -> jobs.Rerun:
        ran.append(list(names))
        return jobs.Rerun(tuple(names), True, "NSE end-of-day: 1 day added")

    monkeypatch.setattr(jobs, "rerun", rerun)
    jobrun.dead_letter("data", "feed", "HTTP 503", remedy={"rerun": ["NSE end-of-day"]}, now=NOW)
    (done,) = oncall.handle(now=NOW, runbooks=desk / "docs" / "RUNBOOKS")
    assert done.ok and done.remedy == "rerun_feed" and ran == [["NSE end-of-day"]]
    assert jobrun.dead_letters() == [], "settled, so it is not worked twice"
    (row,) = oncall.incidents()
    assert row["ok"] and row["runbook"] == "docs/RUNBOOKS/daily-feed-is-stale.md"
    text = (desk / "docs" / "RUNBOOKS" / "daily-feed-is-stale.md").read_text()
    assert "## Incidents" in text and "2026-11-13 data feed: HTTP 503 Fixed" in text


def test_a_remedy_that_fails_stays_open_and_one_off_the_list_is_ticketed(
    desk: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "rerun", lambda names: jobs.Rerun((), False, "still 503"))
    made: list[dict[str, Any]] = []

    class Task:
        id = "T-1"

    def create(**kw: Any) -> Task:
        made.append(kw)
        return Task()

    monkeypatch.setattr("eulerlab.agents.tasks.create", create)
    jobrun.dead_letter("data", "feed", "HTTP 503", remedy={"rerun": ["NSE end-of-day"]}, now=NOW)
    jobrun.dead_letter("autopilot", "write", "KeyError: 'cards'", now=NOW)
    runbooks = desk / "docs" / "RUNBOOKS"
    out = {o.remedy: o for o in oncall.handle(now=NOW, runbooks=runbooks)}
    assert not out["rerun_feed"].ok
    assert out["ticket"].detail == "ticket T-1 for engineering"
    assert made[0]["owner"] == "engineering" and "KeyError" in made[0]["detail"]
    left = jobrun.dead_letters()
    assert [x["name"] for x in left] == ["data"], "the failed fix is kept for the next run"
    assert (runbooks / "ticket-for-engineering.md").read_text().startswith("# A dead letter")


def test_on_call_never_runs_a_remedy_off_its_list() -> None:
    assert oncall.remedy_of({"remedy": {"kind": "shell", "cmd": "rm -rf /"}}) == (
        "ticket",
        {"kind": "shell", "cmd": "rm -rf /"},
    )
    assert set(oncall.ACTIONS) == set(oncall.REMEDIES)


def test_a_planted_position_mismatch_trips_reduce_only(desk: Path) -> None:
    """Issue #148: the broker holds what our journal does not; the book stops adding risk."""
    book = deployments.create("H-0302", mode="paper", capital=100_000, start=date(2026, 11, 2))
    clean = deployments.create("H-0303", mode="paper", capital=100_000, start=date(2026, 11, 2))
    oms = runner.make_oms(book)
    oms.adapter.inject("manual-1", "RELIANCE", Side.BUY, 10, 1300.0)  # type: ignore[attr-defined]
    pages: list[str] = []
    found = oncall.reconcile_books(
        today=date(2026, 11, 13), page=pages.append, now=NOW, runbooks=desk / "docs" / "RUNBOOKS"
    )
    by = {f["book"]: f for f in found}
    assert by[book.id]["breaks"] == ["broker_only RELIANCE: local 0, broker 10"]
    assert by[clean.id]["breaks"] == []
    assert loss_limits.is_reducing(deployments.load(book.id))
    assert not loss_limits.is_reducing(deployments.load(clean.id))
    assert len(pages) == 1 and "reduce-only" in pages[0]
    # A second sweep pages again (the break is still there) but opens no second window.
    oncall.reconcile_books(today=date(2026, 11, 14), page=pages.append, now=NOW,
                           runbooks=desk / "docs" / "RUNBOOKS")  # fmt: skip
    assert len(deployments.load(book.id).reducing) == 1


def test_the_fund_report_is_eight_lines(desk: Path) -> None:
    book = deployments.create("H-0302", mode="paper", capital=100_000, start=date(2026, 11, 2))
    deployments.write_state(
        book,
        {"equity": 101_500.0, "as_of": "2026-11-13",
         "curve": [["2026-11-12", 100_900.0], ["2026-11-13", 101_500.0]]},
    )  # fmt: skip
    oncall.incident("rerun_feed", "data feed: HTTP 503", "re-run", ok=True, now=NOW,
                    runbooks=desk / "docs" / "RUNBOOKS")  # fmt: skip
    report = fund_report.build(NOW)
    assert report["nav"] == 101_500.0 and report["pnl_day"] == 600.0
    (b,) = report["books"]
    assert b["rung"] == "unlisted" and b["pnl_total"] == 1_500.0
    text = fund_report.telegram(report)
    lines = text.splitlines()
    assert len(lines) == 8 and "paper money only" in lines[0]
    assert "Rs +600" in lines[1] and "rerun_feed" in lines[6] and "of Rs 1,000" in lines[7]
    assert Path(fund_report.save(report)).name == "2026-11-13.json"
