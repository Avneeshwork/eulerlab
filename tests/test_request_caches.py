"""The snapshot's live-quote reuse, its deadline, and the bucket listing (ADR-077)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from eulerlab import cloud_results, quotes
from eulerlab import workspace as workspace_mod
from eulerlab.api import server


def test_a_deadline_returns_when_it_expires_not_when_the_work_ends() -> None:
    """The `with` block it replaced waited out the abandoned call: a 3 s hang
    behind a 0.5 s deadline took 3 s."""
    release = threading.Event()
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        server._bounded(release.wait, 5.0, timeout=0.2)
    assert time.monotonic() - started < 1.0
    release.set()


def test_a_complete_answer_is_reused_and_a_failed_one_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    answers: list[tuple[dict[str, Any], str]] = [
        ({"AAA": "q"}, "TimeoutError: cut short"),
        ({"AAA": "q"}, ""),
    ]

    def universe(symbols: list[str]) -> tuple[dict[str, Any], str]:
        calls.append("asked")
        return answers[min(len(calls), len(answers)) - 1]

    monkeypatch.setattr(quotes, "nse_universe", universe)

    assert server._universe_quotes(["AAA"])[1] == "TimeoutError: cut short"
    assert server._universe_quotes(["AAA"]) == ({"AAA": "q"}, "")
    assert server._universe_quotes(["AAA"]) == ({"AAA": "q"}, "")
    assert calls == ["asked", "asked"], "the partial answer was asked again; the whole one was not"

    monkeypatch.setattr(server, "LIVE_UNIVERSE_TTL", 0.0)
    server._universe_quotes(["AAA"])
    assert len(calls) == 3, "an expired answer is asked again"


class _Bucket:
    def __init__(self) -> None:
        self.keys = {"results/default/a.jsonl": 1}
        self.lists = 0

    def list_sizes(self, prefix: str) -> dict[str, int]:
        self.lists += 1
        return {k: v for k, v in self.keys.items() if k.startswith(prefix)}


@pytest.fixture
def bucket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Bucket:
    found = _Bucket()

    class _Config:
        bucket = "test-bucket"

    monkeypatch.setattr(cloud_results, "configured", lambda: (True, ""))
    monkeypatch.setattr(cloud_results, "open_store", lambda: found)
    monkeypatch.setattr(server, "load_storage_config", lambda path: _Config())
    monkeypatch.setattr(workspace_mod, "ROOT", tmp_path)
    tenant = workspace_mod.Workspace(id="default")
    monkeypatch.setattr(workspace_mod, "resolve", lambda name=None: tenant)
    return found


def test_the_bucket_listing_is_reused_until_a_mirror_or_a_refresh(
    bucket: _Bucket, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = server.cloud_status()
    assert first["reachable"] and first["remote_files"] == ["a.jsonl"]
    assert first["listed_at"]

    bucket.keys["results/default/b.jsonl"] = 1
    assert server.cloud_status()["remote_files"] == ["a.jsonl"], "kept inside the window"
    assert bucket.lists == 1

    assert server.cloud_status(refresh=True)["remote_files"] == ["a.jsonl", "b.jsonl"]
    assert bucket.lists == 2

    bucket.keys["results/default/c.jsonl"] = 1
    monkeypatch.setattr(cloud_results, "mirror_quietly", lambda workspace: cloud_results.Mirror())
    server._mirror(workspace_mod.Workspace(id="default"))
    assert server.cloud_status()["remote_files"] == ["a.jsonl", "b.jsonl", "c.jsonl"], (
        "a mirror from this server must not leave the old listing on screen"
    )


def _quote(symbol: str, last: float, source: str = "zerodha") -> quotes.Quote:
    return quotes.Quote(symbol, last, 100.0, source, "2026-10-16T09:20:00+00:00")


def test_movers_the_map_priced_are_not_asked_for_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kite was asked for every mover in the same request. One it priced is
    reused; one it did not goes to the fallback only, never back to Kite."""
    asked: list[list[str]] = []

    def yahoo(symbols: list[str]) -> tuple[dict[str, quotes.Quote], str]:
        asked.append(symbols)
        return {s: _quote(s, 99.0, "yahoo") for s in symbols}, ""

    def kite(*_: object, **__: object) -> None:
        raise AssertionError("Kite was asked again for a mover it had just been asked for")

    monkeypatch.setattr(quotes, "from_yahoo", yahoo)
    monkeypatch.setattr(quotes, "live", kite)
    monkeypatch.setattr(quotes, "from_zerodha", kite)

    band = server._quotes_band(["AAA", "BBB"], held={"AAA": _quote("AAA", 101.0)})

    assert asked == [["BBB"]], "only the mover the map did not price is asked"
    assert band["quotes"]["AAA"]["last"] == 101.0 and band["quotes"]["AAA"]["source"] == "zerodha"
    assert band["quotes"]["BBB"]["source"] == "yahoo"
    assert band["sources"] == {"zerodha": 1, "yahoo": 1}

    asked.clear()
    covered = server._quotes_band(["AAA"], held={"AAA": _quote("AAA", 101.0)})
    assert asked == [] and covered["available"] and covered["source"] == "zerodha"


def test_without_the_maps_answer_the_movers_are_asked_broker_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[list[str]] = []

    def live(symbols: list[str]) -> quotes.QuoteResult:
        asked.append(symbols)
        return quotes.QuoteResult(
            quotes={s: _quote(s, 101.0) for s in symbols}, sources={"zerodha": 1}
        )

    monkeypatch.setattr(quotes, "live", live)
    band = server._quotes_band(["AAA"], held={})
    assert asked == [["AAA"]] and band["source"] == "zerodha"


def test_after_a_429_yahoo_is_not_asked_until_the_backoff_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error
    import urllib.request

    requests: list[str] = []

    def blocked(request: urllib.request.Request, timeout: float) -> None:
        requests.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", blocked)

    assert quotes.from_yahoo(["AAA", "BBB"]) == ({}, quotes.YAHOO_BLOCKED)
    assert quotes.from_yahoo(["CCC"]) == ({}, quotes.YAHOO_BLOCKED)
    assert len(requests) == 1, "one 429, then no request inside the backoff"

    monkeypatch.setattr(quotes, "_yahoo_blocked_until", [0.0])
    quotes.from_yahoo(["DDD"])
    assert len(requests) == 2, "asked again once the backoff has passed"
