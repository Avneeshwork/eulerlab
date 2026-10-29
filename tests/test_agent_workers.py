"""Each agent's own logic, with fakes for the network, the model and the panel."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from eulerlab.agents import knowledge_index, runtime
from eulerlab.agents.spec import AgentSpec, Effective, effective
from eulerlab.agents.workers import (
    engineering,
    market_brief,
    operations,
    portfolio,
    research,
    skeptic,
)


def _agent(name: str, worker: str, **extra: Any) -> dict[str, Effective]:
    spec = AgentSpec(
        name=name,
        title=f"{name} agent",
        job="a job for the test",
        worker=f"eulerlab.agents.workers.{worker}",
        **extra,
    )
    return {name: effective(spec, None)}


# --- skeptic ---


def _curve(n: int = 900, start: date = date(2019, 1, 1)) -> tuple[list[date], list[float]]:
    days = [start + timedelta(days=i) for i in range(n)]
    values = [100.0]
    for i in range(1, n):
        values.append(values[-1] * (1 + 0.0008 + 0.01 * math.sin(i)))
    return days, values


def test_the_skeptic_measures_without_the_best_year_and_the_stress_windows() -> None:
    days, values = _curve()
    found = skeptic.attacks(days, values, {})
    assert found["sessions"] == len(values) - 1
    assert found["best_year"] in (2019, 2020, 2021)
    assert isinstance(found["sharpe_without_best_year"], float)
    assert any(w["name"] == "COVID crash" for w in found["stress_windows"])
    assert found["t_stat"] is not None


def test_the_skeptic_refuses_a_short_curve_and_flags_one_lucky_year() -> None:
    days, values = _curve(10)
    assert "error" in skeptic.attacks(days, values, {})
    items = skeptic.verdicts({"sharpe": 2.0, "sharpe_without_best_year": 0.2, "best_year": 2020})
    assert items[0].severity == "critical"


def test_the_skeptic_reads_a_named_report(tmp_path: Path) -> None:
    days, values = _curve()
    report = tmp_path / "r.json"
    report.write_text(
        json.dumps({"equity": {"days": [d.isoformat() for d in days], "values": values}})
    )
    out = runtime.run(
        "skeptic",
        args={"report": str(report)},
        root=tmp_path / "agents",
        agents=_agent("skeptic", "skeptic"),
    )
    assert out.status == "ok" and "Sharpe" in out.summary


# --- research ---


def test_the_librarian_finds_a_repeat_and_the_scout_names_missing_data(tmp_path: Path) -> None:
    (tmp_path / "H-0001.yaml").write_text(
        "id: H-0001\ntitle: Short-term reversal in large caps\nstatus: dead\nclaim: weekly losers beat weekly winners\n"
    )
    cards = research.known_cards(tmp_path)
    match, score = research.nearest(
        "Short-term reversal: weekly losers beat winners in large caps", cards
    )
    assert match is not None and match.id == "H-0001" and score >= research.REPEAT
    assert research.data_needs("earnings surprise and implied vol") == [
        "Fundamentals",
        "Nifty options",
    ]


def test_research_refuses_without_a_topic(tmp_path: Path) -> None:
    out = runtime.run(
        "research",
        root=tmp_path,
        agents=_agent("research", "research", uses_model=True, daily_requests=5),
    )
    assert out.status == "refused"


# --- engineering ---


def test_engineering_flags_owned_files_missing_docs_and_untested_source(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("y = 1  # ASSUMPTION: nobody checked\n")
    items = engineering.review(["src/x.py", "mandate.yaml"], docs_ok=False, repo=tmp_path)
    titles = " | ".join(i.title for i in items)
    assert "operator-owned" in titles and "no documentation" in titles
    assert "no test changed" in titles and "no A-NNN id" in titles


# --- portfolio and operations ---


def test_inverse_vol_weights_respect_the_cap_and_sum_to_one() -> None:
    w = portfolio.weights({"a": 0.05, "b": 0.20, "c": 0.20}, cap=0.4)
    assert max(w.values()) <= 0.4 + 1e-9
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-3)


def test_step_report_warns_near_a_deadline_and_on_a_miss() -> None:
    rows = [
        {"job": "feed: price panel", "seconds": s, "ok": True, "finished": f"2026-10-{i + 1:02d}"}
        for i, s in enumerate([100, 100, 85])
    ]
    report, items = operations.step_report(rows, {"feed: price panel": 100}, 0.8)
    assert report[0]["latest"] == 85 and items[0].severity == "warn"
    rows.append({"job": "feed: price panel", "seconds": 130, "ok": True, "finished": "2026-10-09"})
    _, items = operations.step_report(rows, {"feed: price panel": 100}, 0.8)
    assert items[0].severity == "critical"


# --- market brief ---


def test_the_market_brief_says_what_it_does_not_hold() -> None:
    sections = market_brief.compose(
        "pre-open", {"context": {}, "world": [], "events": [], "books": [], "data": []}
    )
    text = market_brief.render("pre-open", "2026-10-29", sections, "")
    assert text.startswith("PRE-OPEN BRIEF") and "not held" in text
    assert "COMMENTARY" not in text


def test_the_market_brief_skips_when_nothing_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(market_brief, "_context", lambda notes: {})
    monkeypatch.setattr(market_brief, "_world", lambda notes, fetch: [])
    monkeypatch.setattr(market_brief, "_events", lambda day: [])
    monkeypatch.setattr(market_brief, "_books", list)
    agents = _agent("market_brief", "market_brief")
    now = datetime(2026, 10, 29, 3, 0, tzinfo=UTC)
    first = runtime.run("market_brief", root=tmp_path, agents=agents, now=now)
    assert first.status == "ok" and first.data["text"]
    again = runtime.run(
        "market_brief", root=tmp_path, agents=agents, now=now + timedelta(minutes=5)
    )
    assert again.status == "skipped"
    forced = runtime.run(
        "market_brief",
        args={"force": "1"},
        root=tmp_path,
        agents=agents,
        now=now + timedelta(minutes=6),
    )
    assert forced.status == "ok"


# --- knowledge index ---


def test_the_knowledge_index_finds_a_note_by_its_words(tmp_path: Path) -> None:
    (tmp_path / "docs" / "DECISIONS").mkdir(parents=True)
    (tmp_path / "docs" / "DECISIONS" / "ADR-001-x.md").write_text(
        "# ADR-001 Delivery percentage as a feature\nWe use delivery."
    )
    (tmp_path / "docs" / "DECISIONS" / "ADR-002-y.md").write_text(
        "# ADR-002 Option chain storage\nParquet."
    )
    entries = knowledge_index.build(tmp_path, tmp_path / "agents")
    hits = knowledge_index.search("delivery percentage", entries)
    assert hits and "ADR-001" in hits[0]["title"]
