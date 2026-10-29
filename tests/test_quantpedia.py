"""Quantpedia as a research source: landing once, resuming, and finding leads."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eulerlab.research import quantpedia

DETAIL = {
    "id": "q1",
    "name": "Commodity momentum",
    "description": "Buy commodity futures with the best 12-month return",
    "keywords": ["momentum", "commodities"],
    "instruments": ["futures"],
    "paperMetrics": {"sharpeRatio": "0.6"},
    "calculatedMetrics": {"sharpeRatioInception": 0.31},
    "sourcePaper": {"name": "Momentum in commodities", "abstract": "We find...", "fileId": "p1"},
}


def _fake(calls: list[str]) -> quantpedia.Fetch:
    def fetch(path: str) -> bytes:
        calls.append(path)
        if path == "strategy":
            return json.dumps([{"id": "q1"}, {"id": "q2"}]).encode()
        ident = path.split("/")[-1]
        return json.dumps({**DETAIL, "id": ident, "name": f"{DETAIL['name']} {ident}"}).encode()

    return fetch


def test_sync_lands_each_response_once_and_resumes(tmp_path: Path) -> None:
    calls: list[str] = []
    day = datetime(2026, 10, 29, tzinfo=UTC)
    first = quantpedia.sync(limit=1, fetch=_fake(calls), landing=tmp_path, now=day, pause=0)
    assert first["landed"] == 1 and first["remaining"] == 1
    second = quantpedia.sync(limit=5, fetch=_fake(calls), landing=tmp_path, now=day, pause=0)
    assert second["landed"] == 1 and second["remaining"] == 0
    assert calls.count("strategy") == 1  # the day's list is not fetched twice
    assert calls.count("strategy/q1") == 1
    manifest = [json.loads(x) for x in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert len(manifest) == 3 and all(len(r["sha256"]) == 64 for r in manifest)


def test_no_credentials_is_said_not_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTPEDIA_USERNAME", "")
    monkeypatch.setenv("QUANTPEDIA_API_KEY", "")
    monkeypatch.setattr("eulerlab.env.load_env", lambda *a, **k: {})
    result = quantpedia.sync(landing=tmp_path, pause=0)
    assert not result["ok"] and "QUANTPEDIA_API_KEY" in result["error"]


def test_catalogue_and_leads_find_the_topic(tmp_path: Path) -> None:
    quantpedia.sync(fetch=_fake([]), landing=tmp_path, pause=0)
    entries = quantpedia.catalogue(tmp_path)
    assert entries[0]["sharpe_paper"] == 0.6 and entries[0]["paper"] == "Momentum in commodities"
    found = quantpedia.leads("commodity momentum", entries)
    assert found and found[0].score > 0
    assert quantpedia.leads("bond carry", entries) == []
