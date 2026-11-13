"""The knowledge base (ADR-180): paper, claim, card, result, and the three questions agents ask."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from eulerlab.research import knowledge

NOW = datetime(2026, 11, 13, 10, tzinfo=UTC)

PAPER: dict[str, Any] = {
    "id": "smith-2019-earnings-reversal-india",
    "title": "Short-term reversal after quarterly results in India",
    "markets": ["Indian large caps, daily, 2008-2018"],
    "summary": "Stocks that fall hard on the results day partly recover over the next week.",
    "trade_idea": "Buy stocks that fell 4% or more on their results day and hold for five days.",
    "implementation": "Daily close to close over a week.",
    "reported_results": "About 60 bps over five days before costs.",
    "source_url": "https://example.org/paper.pdf",
}
PID = str(PAPER["id"])


def _card(h: str, **more: Any) -> dict[str, Any]:
    return {"id": h, "title": f"card {h}", "claim": "", "rationale": "", **more}


@pytest.fixture
def lib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EULERLAB_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "research" / "papers").mkdir(parents=True)
    (tmp_path / "hypotheses").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "research" / "papers" / f"{PAPER['id']}.yaml").write_text(yaml.safe_dump(PAPER))
    cards = {
        "H-0001": _card(
            "H-0001",
            title="Results-day losers bounce over a week (paper form)",
            claim="Buy results-day losers, hold five days.",
            source={"paper": PAPER["id"], "replicates": True},
            result="Screen 2026-11-01: net Sharpe -0.2. Screen fail; not gated.",
        ),
        "H-0002": _card(
            "H-0002",
            title="Results-day losers bounce intraday, delivery-filtered",
            claim="Buy at the open the day after a results-day fall.",
            source={"claim": knowledge.claim_id(PID)},
            result="Autopilot screen 2026-11-05: clean. Gate: PAPER.",
        ),
        "H-0003": _card("H-0003", title="Gap-ups fade by the close", source={}),
    }
    for h, card in cards.items():
        (tmp_path / "hypotheses" / f"{h}.yaml").write_text(yaml.safe_dump(card))
    (tmp_path / "docs" / "HISTORY.md").write_text(
        "# History\n\n## 85. The paper's reversal did not survive costs\nH-0001 lost after costs.\n"
    )
    return tmp_path


def _verdicts() -> dict[str, tuple[str, date]]:
    return {"H-0002": ("PAPER", date(2026, 11, 6))}


def test_a_paper_becomes_one_claim_and_sync_is_idempotent(lib: Path) -> None:
    assert knowledge.sync(now=NOW) == [knowledge.claim_id(PID)]
    assert knowledge.sync(now=NOW) == []
    (claim,) = knowledge.claims().values()
    assert claim.sample == "2008-2018" and claim.horizon == "days"
    assert "60 bps" in claim.effect and claim.source == PAPER["source_url"]


def test_every_card_names_a_claim() -> None:
    assert knowledge.card_claim({"id": "H-9", "source": {"paper": "p"}}) == "claim:p"
    assert knowledge.card_claim({"id": "H-9", "source": {"claim": "claim:q", "paper": "p"}}) == (
        "claim:q"
    )
    assert knowledge.card_claim({"id": "H-9"}) == "agent:H-9"


def test_has_reversal_after_results_been_tried_and_how_did_it_do(lib: Path) -> None:
    """Issue #144's done-when, answered from the tools alone, with links."""
    knowledge.sync(now=NOW)
    done = knowledge.tried(verdicts=_verdicts(), experiments=[{"hypothesis": "H-0001"}])
    held = knowledge.claims()
    near = knowledge.tried_near("short-term reversal after results", done, held)
    assert [r["card"] for r in near][:2] == ["H-0001", "H-0002"] or {
        r["card"] for r in near[:2]
    } == {"H-0001", "H-0002"}
    by = {r["card"]: r for r in near}
    assert by["H-0001"]["outcome"] == "failed" and by["H-0002"]["outcome"] == "passed"
    assert by["H-0001"]["paper"] == f"research/papers/{PAPER['id']}.yaml"
    assert "H-0003" not in by

    (rep,) = knowledge.replicated(done, held)
    assert rep["claim"] == knowledge.claim_id(PID) and rep["held_up"] is False

    bad = knowledge.failed(done, held, "reversal after results")
    assert [r["card"] for r in bad] == ["H-0001"] and "not gated" in bad[0]["why"]


def test_the_tool_answers_with_ids_files_and_the_history_that_names_them(
    lib: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab import forward
    from eulerlab.assistant import tools

    knowledge.sync(now=NOW)
    monkeypatch.setattr(forward, "verdicts", lambda *a, **k: _verdicts())
    text = tools.TOOLS["claim_record"].run({"ask": "failed", "about": "reversal results"})
    assert "H-0001 (hypotheses/H-0001.yaml) failed" in text
    assert f"research/papers/{PAPER['id']}.yaml" in text
    assert "HISTORY: 85. The paper's reversal did not survive costs" in text
    assert "did not hold up" in tools.TOOLS["claim_record"].run({"ask": "replicated"})
    assert "must be" in tools.TOOLS["claim_record"].run({"ask": "guess"})


def test_new_autopilot_and_evolved_cards_carry_their_claim() -> None:
    from eulerlab.agents.workers import autopilot as writer

    (card,) = writer.fallback(1, 0, {})
    raw = yaml.safe_load(
        writer.card_yaml("H-0500", card, day=date(2026, 11, 13), model="", tried_count=0)
    )
    assert raw["source"]["claim"] == "agent:H-0500"
    card["paper"] = "p-2020"
    raw = yaml.safe_load(
        writer.card_yaml("H-0501", card, day=date(2026, 11, 13), model="", tried_count=0)
    )
    assert raw["source"]["claim"] == "claim:p-2020"


def test_only_a_paper_card_can_say_it_replicates() -> None:
    from eulerlab.agents.workers import autopilot as writer

    (card,) = writer.fallback(1, 0, {})
    day = date(2026, 11, 13)
    card["replicates"] = True
    raw = yaml.safe_load(writer.card_yaml("H-0502", card, day=day, model="", tried_count=0))
    assert raw["source"]["replicates"] is False, "no paper, nothing to replicate"
    card["paper"] = "p-2020"
    raw = yaml.safe_load(writer.card_yaml("H-0503", card, day=day, model="", tried_count=0))
    assert raw["source"]["replicates"] is True
