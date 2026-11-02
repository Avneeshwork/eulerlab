"""The agent company (ADR-123): the org chart holds together, and the calendar tells the truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from eulerlab.agents import calendar, org
from eulerlab.agents.runtime import Output
from eulerlab.agents.spec import AgentSpec, load_specs
from tools import schedule_daily

MAKEFILE = Path("Makefile").read_text(encoding="utf-8")


def _spec(name: str, reports_to: str) -> AgentSpec:
    return AgentSpec(
        name=name,
        title=name.title(),
        reports_to=reports_to,
        job="A job described in a sentence.",
        worker="eulerlab.agents.workers.data",
    )


def _org(*, outside: str = "gate") -> org.Org:
    head = {"title": "Head", "assigns": "work", "passes_up": "results"}
    return org.Org.model_validate(
        {
            "ceo": "Operator",
            "departments": [
                {"id": "research", "title": "Research", "head": {"name": "head_research", **head}},
                {"id": "platform", "title": "Platform", "head": {"name": "head_platform", **head}},
            ],
            "outside": [{"id": outside, "title": "Gate and mandate"}],
        }
    )


# --- the committed chart -------------------------------------------------


def test_committed_chart_has_no_problems() -> None:
    specs = load_specs()
    assert org.problems(org.load_org(), specs, org.load_company()) == []


def test_every_committed_agent_names_a_department() -> None:
    departments = {d.id for d in org.load_org().departments}
    for name, spec in load_specs().items():
        assert spec.reports_to in departments, name


def test_the_gate_is_outside_the_chart() -> None:
    chart = org.load_org()
    assert "gate" in {o.id for o in chart.outside}
    assert "gate" not in {d.id for d in chart.departments}


def test_no_head_runs_before_its_worker_exists() -> None:
    # Phase 1 puts the heads on paper only; Phase 3 builds their workers.
    assert not any(d.head.running for d in org.load_org().departments)


def test_every_agent_a_job_runs_is_a_known_agent() -> None:
    specs = load_specs()
    for job in schedule_daily.JOBS.values():
        for name in calendar.agents_in_job(job.command, MAKEFILE):
            assert name in specs, (job.name, name)


# --- what problems() catches ----------------------------------------------


def test_sound_chart_is_clean() -> None:
    specs = {"alpha": _spec("alpha", "research"), "beta": _spec("beta", "platform")}
    assert org.problems(_org(), specs) == []


@pytest.mark.parametrize(
    ("specs", "words"),
    [
        ({"alpha": _spec("alpha", ""), "beta": _spec("beta", "platform")}, "has no reports_to"),
        (
            {"alpha": _spec("alpha", "nowhere"), "beta": _spec("beta", "platform")},
            "unknown department",
        ),
        ({"alpha": _spec("alpha", "gate"), "beta": _spec("beta", "platform")}, "outside the chart"),
        ({"alpha": _spec("alpha", "research")}, "'platform' has no agents"),
        (
            {
                "alpha": _spec("alpha", "research"),
                "head_platform": _spec("head_platform", "platform"),
            },
            "same name as an agent",
        ),
    ],
)
def test_problems_are_named(specs: dict[str, AgentSpec], words: str) -> None:
    assert any(words in p for p in org.problems(_org(), specs))


def test_gate_as_a_department_is_refused() -> None:
    specs = {"alpha": _spec("alpha", "research"), "beta": _spec("beta", "platform")}
    assert any("also a department" in p for p in org.problems(_org(outside="research"), specs))


def test_goals_for_an_unknown_department_are_refused() -> None:
    specs = {"alpha": _spec("alpha", "research"), "beta": _spec("beta", "platform")}
    goal = {"id": "g1", "text": "A goal", "measure": "a log"}
    company = org.Company.model_validate({"name": "X", "departments": {"sales": [goal]}})
    assert any("unknown department 'sales'" in p for p in org.problems(_org(), specs, company))


def test_chart_lists_agents_under_their_department() -> None:
    specs = {"alpha": _spec("alpha", "research"), "beta": _spec("beta", "platform")}
    drawn = org.chart(_org(), specs, org.Company(name="X"))
    assert [[a["name"] for a in d["agents"]] for d in drawn["departments"]] == [["alpha"], ["beta"]]


# --- the calendar -----------------------------------------------------------


@dataclass(frozen=True)
class FakeJob:
    name: str
    command: str
    hour: int
    minute: int
    weekdays: tuple[int, ...]
    what: str = "a job"


FAKE_MAKE = "pre:\n\t-@uv run python -m eulerlab.agents.runtime alpha\n\t-@uv run python -m eulerlab.agents.runtime beta\n\nother: pre\n"
JOBS = [
    FakeJob("pre", "cd {repo} && make pre", 8, 45, (1, 2, 3, 4, 5)),
    FakeJob("close", "cd {repo} && make agent NAME=alpha", 16, 15, (1, 2, 3, 4, 5)),
    FakeJob("feed", "{repo}/tools/daily_guard.sh", 19, 30, ()),
]
MONDAY = date(2026, 11, 2)


def _run(root: Path, agent: str, started_utc: str, status: str = "ok") -> str:
    run_id = started_utc.replace("-", "").replace(":", "")[:15] + "Z-" + agent[:6]
    out = Output(
        agent=agent,
        run_id=run_id,
        started=started_utc,
        finished=started_utc,
        status=status,
        summary=f"{agent} ran",
    )
    folder = root / agent / run_id
    folder.mkdir(parents=True)
    (folder / "output.json").write_text(out.model_dump_json(), encoding="utf-8")
    return run_id


def _build(root: Path, now: datetime) -> dict[str, object]:
    specs = {"alpha": _spec("alpha", "research"), "beta": _spec("beta", "platform")}
    return calendar.build(JOBS, FAKE_MAKE, specs, start=MONDAY, days=1, now=now, root=root)


def _states(built: dict[str, object]) -> dict[str, str]:
    slots = built["slots"]
    assert isinstance(slots, list)
    return {s["job"]: s["state"] for s in slots}


def test_agents_in_job_reads_the_recipe_and_name() -> None:
    assert calendar.agents_in_job("cd x && make pre", FAKE_MAKE) == ["alpha", "beta"]
    assert calendar.agents_in_job("cd x && make agent NAME=alpha", FAKE_MAKE) == ["alpha"]
    assert calendar.agents_in_job("x/tools/daily_guard.sh", FAKE_MAKE) == []
    assert calendar.agents_in_job("cd x && make other", FAKE_MAKE) == []


def test_real_preopen_job_runs_three_agents() -> None:
    job = schedule_daily.JOBS["agents-preopen"]
    assert calendar.agents_in_job(job.command, MAKEFILE) == ["data", "operations", "market_brief"]


def test_ran_partial_missed_and_feed(tmp_path: Path) -> None:
    # 08:45 IST is 03:15 UTC; 16:15 IST is 10:45 UTC.
    _run(tmp_path, "alpha", "2026-11-02T03:16:00+00:00")
    now = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)  # 23:30 IST
    states = _states(_build(tmp_path, now))
    assert states == {"pre": "partial", "close": "missed", "feed": "feed"}


def test_morning_run_is_not_counted_for_the_afternoon(tmp_path: Path) -> None:
    morning = _run(tmp_path, "alpha", "2026-11-02T03:16:00+00:00")
    _run(tmp_path, "beta", "2026-11-02T03:17:00+00:00")
    built = _build(tmp_path, datetime(2026, 11, 2, 18, 0, tzinfo=UTC))
    assert _states(built)["pre"] == "ran"
    assert _states(built)["close"] == "missed"
    slots = built["slots"]
    assert isinstance(slots, list)
    assert slots[0]["agents"][0]["run_id"] == morning


def test_upcoming_and_due(tmp_path: Path) -> None:
    now = datetime(2026, 11, 2, 4, 0, tzinfo=UTC)  # 09:30 IST
    states = _states(_build(tmp_path, now))
    assert states["pre"] == "due"
    assert states["close"] == "upcoming"


def test_a_run_outside_every_slot_is_listed_as_unscheduled(tmp_path: Path) -> None:
    # 07:00 IST: before beta's only slot (08:45). A run after a slot counts for
    # it until the agent's next slot that day, since launchd catches up on wake.
    _run(tmp_path, "beta", "2026-11-02T01:30:00+00:00")
    built = _build(tmp_path, datetime(2026, 11, 2, 18, 0, tzinfo=UTC))
    runs = built["runs"]
    assert isinstance(runs, list)
    assert [(r["agent"], r["scheduled"]) for r in runs] == [("beta", False)]


def test_weekend_has_no_weekday_slots(tmp_path: Path) -> None:
    specs = {"alpha": _spec("alpha", "research"), "beta": _spec("beta", "platform")}
    built = calendar.build(
        JOBS,
        FAKE_MAKE,
        specs,
        start=date(2026, 11, 7),
        days=1,
        now=datetime(2026, 11, 8, tzinfo=UTC),
        root=tmp_path,
    )
    assert _states(built) == {"feed": "feed"}
