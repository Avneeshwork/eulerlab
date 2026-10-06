"""The research library: papers as files, linked to the strategies that test them."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from eulerlab.api import research_routes
from eulerlab.research import library


@pytest.fixture(autouse=True)
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "papers"
    monkeypatch.setattr(library, "ROOT", folder)
    return folder


def paper(**changes: object) -> library.Paper:
    raw: dict[str, object] = {
        "title": "A Test Paper About Breakouts",
        "authors": "Smith, J., Doe, A.",
        "year": 2025,
        "summary": "What it found.",
        "trade_idea": "Why it should work.",
        "implementation": "Line one.\nLine two.",
        "red_flags": ["Small sample."],
    }
    raw.update(changes)
    return library.Paper.model_validate(raw)


def test_a_paper_gets_an_id_from_its_author_year_and_title() -> None:
    assert paper().with_id().id == "smith-2025-a-test-paper-about-breakouts"


def test_a_saved_paper_reads_back_unchanged(root: Path) -> None:
    saved = library.save(paper(id="p-one"))
    assert saved == root / "p-one.yaml"
    loaded = library.load("p-one")
    assert loaded == paper(id="p-one", added=loaded.added if loaded else "")
    # Multi-line text is kept as a block, so the file diffs line by line.
    assert "implementation: |" in saved.read_text(encoding="utf-8")


def test_every_paper_needs_its_summary_idea_and_logic() -> None:
    for field in ("summary", "trade_idea", "implementation"):
        with pytest.raises(ValidationError):
            paper(**{field: ""})


def test_a_hypothesis_must_name_a_hypothesis_file() -> None:
    with pytest.raises(ValidationError, match="H-0001"):
        paper(hypothesis="hypothesis one")


def test_a_paper_id_is_never_a_path() -> None:
    assert library.load("../../etc/passwd") is None
    with pytest.raises(ValidationError):
        paper(id="../escape")


def test_the_endpoint_returns_errors_as_sentences() -> None:
    response = research_routes.save_paper(research_routes.PaperRequest(paper={"title": "x"}))
    assert response["ok"] is False
    assert response["errors"]


def test_linking_a_strategy_marks_the_paper_specified() -> None:
    library.save(paper(id="p-two"))
    out = research_routes.add_link(
        "p-two", research_routes.LinkRequest(link={"kind": "registered", "id": "orb_breakout"})
    )
    assert out["ok"] is True
    loaded = library.load("p-two")
    assert loaded is not None
    assert loaded.status == "specified"
    assert [(s.kind, s.id) for s in loaded.strategies] == [("registered", "orb_breakout")]
    again = research_routes.add_link(
        "p-two", research_routes.LinkRequest(link={"kind": "registered", "id": "orb_breakout"})
    )
    assert again.get("unchanged") is True


def test_a_linked_registered_strategy_shows_its_title() -> None:
    library.save(paper(id="p-three", strategies=[{"kind": "registered", "id": "orb_breakout"}]))
    views = research_routes.papers()["papers"]
    link = views[0]["links"][0]
    assert link["exists"] is True
    assert link["title"] != "orb_breakout"


def test_the_seeded_papers_in_the_repository_are_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(library, "ROOT", Path("research/papers"))
    papers = library.all_papers()
    assert {p.id for p in papers} >= {
        "protective-collar-2026-tweezer-bottom",
        "mesfin-2026-structural-limits-intraday",
        "zarattini-2024-profitable-day-trading",
    }
    for p in papers:
        assert p.summary and p.trade_idea and p.implementation and p.red_flags
