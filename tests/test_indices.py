"""Index levels — reading the sweep, and where it is read from."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eulerlab import indices


def _payload() -> dict[str, object]:
    return {
        "taken_at": "2026-08-24T09:00:00+00:00",
        "india": [
            {
                "symbol": "NIFTY 50",
                "name": "NIFTY 50",
                "last": 24_300.0,
                "change_pct": 0.2,
                "region": "IN",
                "source": "zerodha",
            }
        ],
        "world": [],
        "crypto": [],
        "fx": [],
        "movers": [],
        "sectors": [],
        "errors": {},
    }


def test_a_missing_sweep_reads_as_none_not_empty(tmp_path: Path) -> None:
    """ "Not swept yet" and "swept, everything flat" look identical once the
    levels are gone, and only one of them means run `make world`."""
    assert indices.load(root=tmp_path, allow_cloud=False) is None


def test_the_newest_sweep_wins(tmp_path: Path) -> None:
    (tmp_path / "2026-08-23.json").write_text(json.dumps({"taken_at": "old"}), encoding="utf-8")
    (tmp_path / "2026-08-24.json").write_text(json.dumps(_payload()), encoding="utf-8")
    loaded = indices.load(root=tmp_path, allow_cloud=False)
    assert loaded is not None
    assert loaded["taken_at"] == "2026-08-24T09:00:00+00:00"


def test_a_pruned_sweep_is_not_a_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug this test exists for.

    `prune-local` moves landed files to B2 and leaves the tree empty, so a
    local-only glob reported a swept file as never taken and the entire index
    ribbon went blank the first time a prune followed a sweep. The landing zone
    is the union of disk and bucket; a reader that forgets it works right up
    until the next prune.
    """
    from eulerlab.ingest import landing_reader

    calls: list[tuple[str, str]] = []

    def fake_available(tree: str, pattern: str = "**/*", **_: object) -> list[str]:
        calls.append((tree, pattern))
        return ["marketdata/2026-08-24.json"]

    def fake_read(relative: str, **_: object) -> bytes:
        return json.dumps(_payload()).encode("utf-8")

    monkeypatch.setattr(landing_reader, "available", fake_available)
    monkeypatch.setattr(landing_reader, "read", fake_read)

    loaded = indices.load(root=tmp_path)  # empty directory, cloud allowed
    assert loaded is not None, "a pruned sweep must still load"
    assert calls == [("marketdata", "*.json")]


def test_a_lone_paywalled_index_does_not_hide_the_rest() -> None:
    """Coverage is per instrument on the free plan — S&P, Nasdaq, Dow and FTSE
    answer while DAX does not. Breaking on the first refusal meant NIKKEI and
    HANG SENG were never asked, and four of seven read as all there was."""
    assert len(indices.WORLD) == 7
    assert {name for _, name, _ in indices.WORLD} >= {"NIKKEI 225", "HANG SENG"}


def test_usd_inr_leads_the_pairs_after_the_euro() -> None:
    """Whatever the global convention about majors, USD/INR is the pair that
    actually reprices an Indian book overnight."""
    assert [name for _, name, _ in indices.FX][:2] == ["EUR/USD", "USD/INR"]
