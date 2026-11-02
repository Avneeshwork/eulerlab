"""The agent company: departments, their heads, the agents under them, and goals (ADR-122).

    you (CEO) ──┬── Head of Research ──────────── research, lab, skeptic, ...
                ├── Head of Data and Platform ─── data, engineering, operations
                └── Head of Portfolio and Risk ── portfolio, market_brief
    gate and mandate: outside the chart, answer only to you

`config/org.yaml` holds the structure, `config/company.yaml` the goals, and each
agent's own definition names its department in `reports_to`. The depth is fixed
(agent → head → CEO), so a loop or a second manager cannot be written down; what
can go wrong is a missing or unknown department, a head named like an agent, or
the gate put inside a department. `problems` lists those, and a test fails on any.

This module only reads. Heads with `running: false` exist on paper until the
manager workers are built; nothing here assigns work or approves anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.agents.spec import NAME_PATTERN, AgentSpec

ORG_PATH = Path("config/org.yaml")
COMPANY_PATH = Path("config/company.yaml")
ID_PATTERN = r"^[a-z][a-z0-9_-]{1,31}$"


class Head(BaseModel):
    """A department's manager. `running` stays false until it has a worker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=NAME_PATTERN)
    title: str = Field(min_length=3, max_length=80)
    running: bool = False
    assigns: str = Field(min_length=3, max_length=200)
    passes_up: str = Field(min_length=3, max_length=200)


class Department(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=3, max_length=80)
    head: Head


class Outside(BaseModel):
    """Something that answers to the CEO but is no one's employee: the gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=3, max_length=80)
    note: str = ""


class Org(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ceo: str = Field(min_length=1, max_length=80)
    departments: list[Department] = Field(min_length=1)
    outside: list[Outside] = Field(default_factory=list)


class Goal(BaseModel):
    """A goal and how it is measured. Only the operator moves it to `approved`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    text: str = Field(min_length=3, max_length=200)
    measure: str = Field(min_length=3, max_length=200)
    status: Literal["proposed", "approved", "retired"] = "proposed"


class Company(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    goals: list[Goal] = Field(default_factory=list)
    departments: dict[str, list[Goal]] = Field(default_factory=dict)


def _read(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        msg = f"{path} must hold a mapping"
        raise ValueError(msg)
    return raw


def load_org(path: Path = ORG_PATH) -> Org:
    return Org.model_validate(_read(path))


def load_company(path: Path = COMPANY_PATH) -> Company:
    return Company.model_validate(_read(path))


def problems(org: Org, specs: dict[str, AgentSpec], company: Company | None = None) -> list[str]:
    """Everything wrong with the chart, in words. Empty means it is sound."""
    found: list[str] = []
    ids = [d.id for d in org.departments]
    heads = [d.head.name for d in org.departments]
    outside = {o.id for o in org.outside}
    for label, values in (("department id", ids), ("head name", heads)):
        repeats = sorted({v for v in values if values.count(v) > 1})
        if repeats:
            found.append(f"repeated {label}: {', '.join(repeats)}")
    for head in heads:
        if head in specs:
            found.append(f"head {head!r} has the same name as an agent")
    for name in sorted(outside & set(ids)):
        found.append(f"{name!r} is outside the chart and also a department")
    for name in sorted(outside & set(specs)):
        found.append(f"{name!r} is outside the chart and also an agent")
    for name, spec in sorted(specs.items()):
        if not spec.reports_to:
            found.append(f"agent {name!r} has no reports_to")
        elif spec.reports_to in outside:
            found.append(
                f"agent {name!r} reports to {spec.reports_to!r}, which is outside the chart"
            )
        elif spec.reports_to not in ids:
            found.append(f"agent {name!r} reports to unknown department {spec.reports_to!r}")
    staffed = {spec.reports_to for spec in specs.values()}
    for dept in ids:
        if dept not in staffed:
            found.append(f"department {dept!r} has no agents")
    if company is not None:
        for dept in sorted(set(company.departments) - set(ids)):
            found.append(f"goals for unknown department {dept!r}")
        goal_ids = [g.id for g in company.goals] + [
            g.id for goals in company.departments.values() for g in goals
        ]
        repeats = sorted({g for g in goal_ids if goal_ids.count(g) > 1})
        if repeats:
            found.append(f"repeated goal id: {', '.join(repeats)}")
    return found


def department_of(specs: dict[str, AgentSpec]) -> dict[str, str]:
    """Agent name → department id."""
    return {name: spec.reports_to for name, spec in specs.items()}


def chart(org: Org, specs: dict[str, AgentSpec], company: Company) -> dict[str, Any]:
    """The chart as the AI tab draws it: CEO, departments with head, agents and goals."""

    def goals(items: list[Goal]) -> list[dict[str, str]]:
        return [g.model_dump() for g in items]

    return {
        "ceo": org.ceo,
        "company": company.name,
        "goals": goals(company.goals),
        "departments": [
            {
                "id": d.id,
                "title": d.title,
                "head": d.head.model_dump(),
                "goals": goals(company.departments.get(d.id, [])),
                "agents": [
                    {"name": name, "title": spec.title, "job": spec.job, "enabled": spec.enabled}
                    for name, spec in sorted(specs.items())
                    if spec.reports_to == d.id
                ],
            }
            for d in org.departments
        ],
        "outside": [o.model_dump() for o in org.outside],
        "problems": problems(org, specs, company),
    }
