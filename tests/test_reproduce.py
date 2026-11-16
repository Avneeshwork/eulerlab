"""Data and code stamps on every experiment, and re-running one (#154, ADR-213)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.research import data_manifest, experiments, lang, reproduce
from test_research_bench import _fast, _panel, folder  # noqa: F401  (fixture)

NOW = datetime(2026, 11, 16, 6, tzinfo=UTC)
FADE = lang.Spec(shape="event", kind="intraday", side="short", when="ge(gap, 0.02)", score="gap")


def _row(fast: Any) -> dict[str, Any]:
    found = fast.screen(FADE)
    daily = fast.returns.pop(FADE.fingerprint())
    made = experiments.record(
        purpose="screen",
        fingerprint=FADE.fingerprint(),
        first=FADE.first,
        end=max(daily),
        metrics={"count": found["count"], "net_sharpe": found["net"]["sharpe"]},
        daily=daily,
        now=NOW,
        spec=FADE.model_dump(mode="json"),
    )
    return next(r for r in experiments.rows() if r["id"] == made)


def test_every_row_names_its_data_and_its_commit(folder: Path) -> None:  # noqa: F811
    row = _row(_fast(_panel(fade=True)))
    assert row["data_version"] == data_manifest.version()
    assert set(row["code"]) == {"commit", "dirty"} and row["code"]["commit"]


def test_a_row_reruns_to_the_same_answer(folder: Path) -> None:  # noqa: F811
    data = _panel(fade=True)
    row = _row(_fast(data))
    out = reproduce.reproduce(row, engine=lambda end: _fast(data))
    assert out["result"] == "reproduced", out
    assert out["returns"]["moved"] == 0


def test_a_changed_history_says_which_day_moved(folder: Path) -> None:  # noqa: F811
    row = _row(_fast(_panel(fade=True)))
    out = reproduce.reproduce(row, engine=lambda end: _fast(_panel()))
    assert out["result"].startswith("moved")
    assert out["returns"]["moved"] > 0 and out["returns"]["first_moved"]


def test_the_manifest_hashes_content_and_rehashes_only_a_changed_file(
    folder: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = folder / "data" / "derived" / "price_panel.jsonl"
    panel.parent.mkdir(parents=True, exist_ok=True)
    panel.write_text('{"d": "2024-01-01"}\n')
    first = data_manifest.manifest()
    assert first["delivery"] == "absent" and first["panel"] != "absent"
    calls: list[Path] = []
    real = data_manifest._sha256

    def counted(path: Path) -> str:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(data_manifest, "_sha256", counted)
    assert data_manifest.manifest() == first and calls == []  # unchanged: read from the cache
    panel.write_text('{"d": "2024-01-02"}\n')
    assert data_manifest.manifest()["panel"] != first["panel"] and calls == [panel]
    assert data_manifest.version() != data_manifest.version(first)
