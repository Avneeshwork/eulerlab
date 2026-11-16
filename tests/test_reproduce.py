"""Data and code stamps on every experiment, and re-running one (#154, ADR-213)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.research import data_manifest, experiments, lang, reproduce
from eulerlab.validation import ledger
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


def test_every_ledger_entry_names_its_data_and_its_commit(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    entry = ledger.append(kind="ic", subject="x", params={}, outcome={}, path=path)
    assert entry.data_version == data_manifest.version()
    assert entry.code is not None and set(entry.code) == {"commit", "dirty"}
    assert ledger.read(path)[0] == entry and ledger.verify_chain(path).intact


def test_an_entry_from_before_the_stamps_still_verifies(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    payload: dict[str, object] = {
        "seq": 1,
        "logged_at": "2026-01-01T00:00:00+00:00",
        "kind": "ic",
        "subject": "old",
        "params": {},
        "outcome": {},
        "prev_hash": ledger.GENESIS,
    }
    old = {**payload, "entry_hash": ledger.compute_hash(payload)}
    path.write_text(json.dumps(old) + "\n")
    ledger.append(kind="ic", subject="new", params={}, outcome={}, path=path)
    first, second = ledger.read(path)
    assert first.data_version is None and second.data_version is not None
    assert ledger.verify_chain(path).intact
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["data_version"] = "0" * 16
    path.write_text(lines[0] + "\n" + json.dumps(tampered) + "\n")
    assert not ledger.verify_chain(path).intact  # the stamp is covered by the hash


def test_the_drift_check_passes_when_every_pinned_row_reproduces(folder: Path) -> None:  # noqa: F811
    data = _panel(fade=True)
    row = _row(_fast(data))
    pinned = [reproduce.Reference(id=row["id"])]
    clean, lines = reproduce.check(pinned, experiments.rows(), engine=lambda end: _fast(data))
    assert clean and lines == [f"{row['id']}: reproduced (rule {FADE.fingerprint()[:12]})"]


def test_the_drift_check_names_the_rule_and_first_day_that_moved(folder: Path) -> None:  # noqa: F811
    row = _row(_fast(_panel(fade=True)))
    pinned = [reproduce.Reference(id=row["id"]), reproduce.Reference(id="nope")]
    clean, lines = reproduce.check(pinned, experiments.rows(), engine=lambda end: _fast(_panel()))
    first = reproduce.reproduce(row, engine=lambda end: _fast(_panel()))["returns"]["first_moved"]
    assert not clean
    assert lines[0].startswith(f"{row['id']}: DRIFT in rule {FADE.fingerprint()[:12]}")
    assert f"first day moved: {first}" in lines[0]
    assert lines[1] == "nope: MISSING, no such row in the experiment store"


def test_the_committed_reference_file_loads_and_a_typo_is_refused(tmp_path: Path) -> None:
    assert isinstance(reproduce.references(), list)  # config/reference_experiments.yaml
    blank = tmp_path / "refs.yaml"
    blank.write_text("rows: []\n")
    assert reproduce.references(blank) == []
    blank.write_text("rows:\n  - id: abc\n    why: test\n")
    assert reproduce.references(blank)[0].id == "abc"
    blank.write_text("rows:\n  - idd: abc\n")
    with pytest.raises(ValueError):
        reproduce.references(blank)


def test_make_reproduce_check_exits_non_zero_on_drift(
    folder: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    row = _row(_fast(_panel(fade=True)))
    refs = tmp_path / "refs.yaml"
    refs.write_text("rows: []\n")
    monkeypatch.setattr(reproduce, "REFERENCES", refs)
    monkeypatch.setattr(reproduce, "_engine", lambda end: _fast(_panel()))
    assert reproduce.main(["--check"]) == 0
    assert "nothing to check" in capsys.readouterr().out
    refs.write_text(f"rows:\n  - id: {row['id']}\n")
    assert reproduce.main(["--check"]) == 1
    assert "DRIFT" in capsys.readouterr().out
