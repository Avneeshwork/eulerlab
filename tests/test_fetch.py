"""Politeness rules, tested without touching a network."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field

import pytest

from eulerlab.ingest import fetch as fetch_module
from eulerlab.ingest.fetch import (
    Fetcher,
    FetchPolicy,
    Outcome,
    TransportError,
)


@dataclass
class FakeTransport:
    """Replays a scripted sequence of responses and records what was asked."""

    script: list[tuple[int, bytes] | Exception]
    calls: list[str] = field(default_factory=list)

    def get(self, url: str, *, timeout: float) -> tuple[int, bytes]:
        self.calls.append(url)
        step = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(step, Exception):
            raise step
        return step


@dataclass
class Clock:
    """Deterministic time. Records every sleep so pacing can be asserted."""

    now: float = 0.0
    slept: list[float] = field(default_factory=list)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def time(self) -> float:
        return self.now


def _fetcher(
    script: list[tuple[int, bytes] | Exception], **policy: float | int
) -> tuple[Fetcher, FakeTransport, Clock]:
    transport = FakeTransport(script)
    clock = Clock()
    fetcher = Fetcher(
        transport,
        FetchPolicy(**policy),  # type: ignore[arg-type]
        sleep=clock.sleep,
        clock=clock.time,
    )
    return fetcher, transport, clock


def test_success_returns_the_payload() -> None:
    fetcher, transport, _ = _fetcher([(200, b"data")])
    result = fetcher.get("https://example.invalid/a.zip")
    assert result.ok
    assert result.payload == b"data"
    assert len(transport.calls) == 1


def test_404_is_absent_and_is_never_retried() -> None:
    # Eleven years of holidays would otherwise cost 4x the requests.
    fetcher, transport, _ = _fetcher([(404, b"")], max_attempts=4)
    result = fetcher.get("https://example.invalid/a.zip")
    assert result.outcome is Outcome.ABSENT
    assert len(transport.calls) == 1


def test_transient_server_error_is_retried_then_succeeds() -> None:
    fetcher, transport, _ = _fetcher([(503, b""), (503, b""), (200, b"ok")], max_attempts=4)
    result = fetcher.get("https://example.invalid/a.zip")
    assert result.ok
    assert len(transport.calls) == 3


def test_retries_are_bounded() -> None:
    fetcher, transport, _ = _fetcher([(503, b"")], max_attempts=3)
    result = fetcher.get("https://example.invalid/a.zip")
    assert result.outcome is Outcome.FAILED
    assert len(transport.calls) == 3
    assert "3 attempts" in result.detail


def test_a_non_retryable_status_gives_up_immediately() -> None:
    fetcher, transport, _ = _fetcher([(403, b"")], max_attempts=4)
    result = fetcher.get("https://example.invalid/a.zip")
    assert result.outcome is Outcome.FAILED
    assert len(transport.calls) == 1


def test_transport_errors_are_retried() -> None:
    fetcher, transport, _ = _fetcher(
        [TransportError("connection reset"), (200, b"ok")], max_attempts=3
    )
    assert fetcher.get("https://example.invalid/a.zip").ok
    assert len(transport.calls) == 2


def test_backoff_grows_and_is_capped() -> None:
    fetcher, _, clock = _fetcher(
        [(503, b"")], max_attempts=5, backoff_base_s=2.0, backoff_cap_s=8.0, min_interval_s=0.0
    )
    fetcher.get("https://example.invalid/a.zip")
    # Jittered to 0.5x-1.5x of 2, 4, 8, 8 (capped).
    assert len(clock.slept) == 4
    assert clock.slept[0] < clock.slept[1]
    assert all(sleep <= 8.0 * 1.5 for sleep in clock.slept)


def test_backoff_is_deterministic_for_a_given_seed() -> None:
    # Project rule: seed everything. Two identical runs must pace identically.
    runs = []
    for _ in range(2):
        fetcher, _, clock = _fetcher([(503, b"")], max_attempts=4, min_interval_s=0.0)
        fetcher.get("https://example.invalid/a.zip")
        runs.append(clock.slept)
    assert runs[0] == runs[1]


def test_requests_are_spaced_by_the_minimum_interval() -> None:
    fetcher, _, clock = _fetcher([(200, b"ok")], min_interval_s=1.5)
    fetcher.get("https://example.invalid/a.zip")
    fetcher.get("https://example.invalid/b.zip")
    assert pytest.approx(1.5) == sum(clock.slept)


def test_the_first_request_is_not_delayed() -> None:
    fetcher, _, clock = _fetcher([(200, b"ok")], min_interval_s=1.5)
    fetcher.get("https://example.invalid/a.zip")
    assert clock.slept == []


def test_no_head_requests_anywhere_in_the_module() -> None:
    """NSE's legacy archive 403s on HEAD but 200s on GET for the same URL.

    Using HEAD as an existence check would report thousands of present trading
    days as missing. This guards the trap described in research note 002.
    """
    source = inspect.getsource(fetch_module)
    assert '"HEAD"' not in source
    assert "'HEAD'" not in source
    assert not hasattr(fetch_module.Transport, "head")
