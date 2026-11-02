"""US bars landing: re-fetching must not restamp or shrink what is held (HISTORY #62)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from eulerlab.ingest import alpaca, landing_reader


def _bar(day: str, close: float, known: str) -> alpaca.Bar:
    return alpaca.Bar(
        symbol="AAA",
        day=day,
        open=1.0,
        high=2.0,
        low=0.5,
        close=close,
        volume=100.0,
        trades=10,
        vwap=1.5,
        knowledge_time=known,
    )


def _rows(path: Path) -> list[dict[str, object]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _feed(monkeypatch: pytest.MonkeyPatch, bars: list[alpaca.Bar]) -> None:
    monkeypatch.setattr(alpaca, "daily_bars", lambda *a, **k: ({"AAA": bars}, ""))


def test_refetching_an_unchanged_bar_keeps_the_file_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed(monkeypatch, [_bar("2026-10-01", 1.2, "2026-10-01T22:00:00+00:00")])
    alpaca.land_bars(["AAA"], start="2026-10-01", root=tmp_path)
    path = alpaca.bars_path("AAA", "2026-10", root=tmp_path)
    first = path.read_bytes()

    _feed(monkeypatch, [_bar("2026-10-01", 1.2, "2026-11-02T14:00:00+00:00")])
    _, new, _ = alpaca.land_bars(["AAA"], start="2026-10-01", root=tmp_path)

    assert new == 0
    assert gzip.decompress(path.read_bytes()) == gzip.decompress(first)
    assert _rows(path)[0]["knowledge_time"] == "2026-10-01T22:00:00+00:00"


def test_a_revised_bar_replaces_the_held_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed(monkeypatch, [_bar("2026-10-01", 1.2, "2026-10-01T22:00:00+00:00")])
    alpaca.land_bars(["AAA"], start="2026-10-01", root=tmp_path)
    _feed(monkeypatch, [_bar("2026-10-01", 1.3, "2026-11-02T14:00:00+00:00")])
    alpaca.land_bars(["AAA"], start="2026-10-01", root=tmp_path)

    rows = _rows(alpaca.bars_path("AAA", "2026-10", root=tmp_path))
    assert [(r["close"], r["knowledge_time"]) for r in rows] == [(1.3, "2026-11-02T14:00:00+00:00")]


def _bucket(
    monkeypatch: pytest.MonkeyPatch, root: Path, held: dict[str, bytes], unreachable: set[str]
) -> None:
    monkeypatch.setattr(alpaca, "LANDING", root)
    monkeypatch.setattr(landing_reader, "cloud_enabled", lambda: True)
    monkeypatch.setattr(landing_reader, "available", lambda tree, pattern: sorted(held))

    def read(relative: str) -> bytes:
        if relative in unreachable:
            raise ConnectionError("bucket unreachable")
        local = root.parent / relative
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(held[relative])
        return held[relative]

    monkeypatch.setattr(landing_reader, "read", read)


def test_a_pruned_month_is_restored_from_the_bucket_before_merging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "us"
    in_bucket = json.dumps(_bar("2026-10-01", 1.2, "2026-10-01T22:00:00+00:00").to_row()) + "\n"
    _bucket(
        monkeypatch,
        root,
        {"us/bars/AAA/2026-10.jsonl.gz": gzip.compress(in_bucket.encode())},
        set(),
    )
    _feed(
        monkeypatch,
        [
            _bar("2026-10-01", 1.2, "2026-11-02T14:00:00+00:00"),
            _bar("2026-10-02", 1.4, "2026-11-02T14:00:00+00:00"),
        ],
    )

    _, new, error = alpaca.land_bars(["AAA"], start="2026-10-01", root=root)

    rows = _rows(alpaca.bars_path("AAA", "2026-10", root=root))
    assert (new, error) == (1, "")
    assert [r["knowledge_time"] for r in rows] == [
        "2026-10-01T22:00:00+00:00",
        "2026-11-02T14:00:00+00:00",
    ]


def test_a_pruned_month_that_cannot_be_fetched_is_not_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "us"
    key = "us/bars/AAA/2026-10.jsonl.gz"
    _bucket(monkeypatch, root, {key: b""}, {key})
    _feed(monkeypatch, [_bar("2026-10-02", 1.4, "2026-11-02T14:00:00+00:00")])

    written, _, error = alpaca.land_bars(["AAA"], start="2026-10-01", root=root)

    assert written == 0
    assert "could not be fetched" in error
    assert not alpaca.bars_path("AAA", "2026-10", root=root).exists()
