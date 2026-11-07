"""The AI tab's pipeline and results, read from what the agents wrote (ADR-151)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.agents import flow
from eulerlab.agents.runtime import Item, Output

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def _write(root: Path, agent: str, run_id: str, started: str, **fields: Any) -> None:
    out = Output(
        agent=agent,
        run_id=run_id,
        started=started,
        finished=started,
        status=fields.pop("status", "ok"),
        summary=fields.pop("summary", f"{agent} did its thing"),
        **fields,
    )
    folder = root / agent / run_id
    folder.mkdir(parents=True)
    (folder / "output.json").write_text(out.model_dump_json(), encoding="utf-8")


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    root, hyp = tmp_path / "agents", tmp_path / "hypotheses"
    hyp.mkdir()
    (hyp / "H-0200.yaml").write_text("id: H-0200\nresult: 'Autopilot screen: net Sharpe 1.1'\n")
    _write(
        root,
        "autopilot",
        "20261107T113000Z-aaaaaa",
        "2026-11-07T11:30:00+00:00",
        data={
            "cards": [
                {"id": "H-0200", "kind": "swing", "rule": "buy new highs"},
                {"id": "H-0201", "kind": "intraday", "rule": "fade gaps"},
                {"id": "H-0202", "kind": "intraday", "rule": "follow deals"},
            ],
            "survivors": ["H-0200", "H-0202"],
            "gates": [{"hypothesis": "H-0200", "verdict": "PROMOTE", "entries": 2}],
            "kept": {"H-0200": {"report": "stored", "paper": "paper book p1"}},
            "note": "docs/RESEARCH/180-autopilot.md",
        },
    )
    _write(
        root,
        "lab",
        "20261107T110000Z-bbbbbb",
        "2026-11-07T11:00:00+00:00",
        data={
            "results": [
                {
                    "card": "c1",
                    "screens": [{"t_stat": -4.3, "passed": False}],
                    "stopped": "no edge",
                },
                {"card": "c2", "screens": [{"t_stat": 3.2, "passed": True}], "survivors": ["x"]},
            ]
        },
    )
    _write(
        root,
        "research",
        "20261107T100000Z-cccccc",
        "2026-11-07T10:00:00+00:00",
        items=[Item(kind="draft", title="Idea one"), Item(kind="draft", title="Idea two")],
        data={"topic": "momentum"},
    )
    # An old research run outside the week: a result, but not in the week's numbers.
    _write(
        root,
        "research",
        "20261020T100000Z-dddddd",
        "2026-10-20T10:00:00+00:00",
        items=[Item(kind="draft", title="Old idea")],
    )
    _write(root, "lab", "20261107T040000Z-eeeeee", "2026-11-07T04:00:00+00:00", status="failed")
    # A support agent runs often: only its newest run is a result.
    _write(root, "data", "20261107T080000Z-ffffff", "2026-11-07T08:00:00+00:00", summary="older")
    _write(
        root,
        "data",
        "20261107T120000Z-ffffff",
        "2026-11-07T12:00:00+00:00",
        summary="newest",
        items=[Item(kind="alert", title="a dataset is late", severity="warn")],
    )
    return root, hyp


def _build(root: Path, hyp: Path) -> dict[str, Any]:
    promotions = [
        {
            "item": "i1",
            "card": "x/c2/card.yaml",
            "hypothesis": "H-0150",
            "verdict": "KILL — 3 of 12 rules failed",
            "started": "2026-11-06T10:00:00+00:00",
            "finished": "2026-11-06T10:30:00+00:00",
            "findings": [
                {"rule": "dsr", "passed": False, "detail": "0.2"},
                {"rule": "cost", "passed": True, "detail": ""},
            ],
        },
    ]
    papers = [
        {
            "id": "p1",
            "strategy_id": "H-0200",
            "status": "active",
            "created_at": "2026-11-07T12:00:00+00:00",
            "capital": 1e6,
        }
    ]
    return flow.build(
        now=NOW,
        root=root,
        promotions=promotions,
        papers=papers,
        names=["autopilot", "lab", "research", "data"],
        hypotheses=hyp,
    )


def test_stages_count_the_last_week(tmp_path: Path) -> None:
    root, hyp = _setup(tmp_path)
    stages = {s["key"]: s for s in _build(root, hyp)["stages"]}
    assert list(stages) == ["find", "write", "test", "gate", "paper"]
    assert stages["find"]["number"] == "2"  # the October drafts are older than a week
    assert stages["write"]["number"] == "3"
    # Two lab cards and three autopilot cards; one lab survivor, two autopilot survivors.
    assert (stages["test"]["number"], stages["test"]["label"]) == ("5", "tested, 3 passed")
    # The approved survivor's KILL and the autopilot's PROMOTE.
    assert (stages["gate"]["number"], stages["gate"]["label"]) == ("2", "gated, 1 passed")
    assert (stages["paper"]["number"], stages["paper"]["label"]) == ("1", "paper books, 1 new")
    assert stages["write"]["last"]["agent"] == "autopilot"


def test_an_autopilot_batch_says_what_happened_to_each_rule(tmp_path: Path) -> None:
    root, hyp = _setup(tmp_path)
    results = _build(root, hyp)["results"]
    batch = next(r for r in results if r["kind"] == "batch")
    rows = {r["id"]: r for r in batch["rows"]}
    assert rows["H-0200"]["status"] == "PROMOTE" and rows["H-0200"]["tone"] == "pass"
    assert rows["H-0200"]["detail"].startswith("Autopilot screen")
    assert rows["H-0201"]["status"] == "Failed test"
    assert rows["H-0202"]["status"].startswith("Passed test")
    assert (
        batch["meaning"]
        == "1 failed the backtest, 1 passed and wait for the gate, 1 gated (1 passed)."
    )
    verdict = next(r for r in results if r["kind"] == "verdict" and "H-0200" in r["title"])
    assert verdict["outcome"] == "pass" and "paper book p1" in verdict["summary"]


def test_results_are_newest_first_and_support_checks_collapse(tmp_path: Path) -> None:
    root, hyp = _setup(tmp_path)
    results = _build(root, hyp)["results"]
    ats = [r["at"] for r in results]
    assert ats == sorted(ats, reverse=True)
    data = [r for r in results if r["agent"] == "data"]
    assert len(data) == 1 and data[0]["summary"] == "newest" and not data[0]["pipeline"]
    assert data[0]["outcome"] == "partial"  # it carries a warning
    assert len([r for r in results if r["agent"] == "research"]) == 2
    problem = next(r for r in results if r["kind"] == "problem")
    assert problem["outcome"] == "fail" and problem["pipeline"]
    kill = next(r for r in results if r["title"].startswith("H-0150"))
    assert kill["outcome"] == "fail" and kill["rows"][0]["tone"] == "fail"  # failed rules first
    assert any(r["kind"] == "paper" for r in results)


def test_a_lab_run_reads_in_plain_words(tmp_path: Path) -> None:
    root, hyp = _setup(tmp_path)
    lab = next(r for r in _build(root, hyp)["results"] if r["kind"] == "test")
    assert [r["status"] for r in lab["rows"]] == ["No edge", "Survived"]
    assert lab["meaning"].startswith("1 survived")


def test_nothing_yet(tmp_path: Path) -> None:
    out = flow.build(now=NOW, root=tmp_path, names=["autopilot"], hypotheses=tmp_path)
    assert out["results"] == []
    assert all(s["number"] == "0" for s in out["stages"])
    assert out["stages"][1]["last"]["status"] == "never"


def test_verdict_words() -> None:
    assert flow.verdict_word("KILL — 3 of 12 rules failed") == "KILL"
    assert flow.verdict_word("PAPER") == "PAPER"
    assert flow.outcome_of("PROMOTE") == "pass"
    assert flow.outcome_of("PAPER") == "partial"
    assert flow.outcome_of("VALIDATE FAILED") == "info"
