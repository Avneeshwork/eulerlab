"""The rate governor: a bound, not an average.

Every test here drives a fake clock. A governor tested against wall-clock time
gets tested loosely — nobody writes a test that sleeps for four seconds — and
loosely tested is how a limit becomes an average.
"""

from __future__ import annotations

import pytest

from eulerlab.config import load_execution
from eulerlab.oms.ems import Governor, RateLimitExceeded


class Clock:
    """A clock that only moves when something sleeps, or is told to."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _governor(clock: Clock, limit: int = 5, *, max_wait: float = 30.0) -> Governor:
    return Governor(limit, clock=clock, sleep=clock.sleep, max_wait=max_wait)


def test_the_default_comes_from_config_not_from_a_literal() -> None:
    """CLAUDE.md: the EMS enforces max_orders_per_second from config. A
    hardcoded 5 here would pass every test and ignore the operator's file."""
    assert Governor().max_per_second == load_execution().max_orders_per_second


def test_the_first_burst_does_not_wait() -> None:
    clock = Clock()
    governor = _governor(clock)
    assert [governor.acquire() for _ in range(5)] == [0.0] * 5


def test_the_sixth_send_waits_for_the_window_to_slide() -> None:
    clock = Clock()
    governor = _governor(clock)
    for _ in range(5):
        governor.acquire()
    assert governor.acquire() == pytest.approx(1.0)
    assert clock.now == pytest.approx(1.0)


def test_no_second_ever_contains_more_than_the_limit() -> None:
    """The property that matters, stated directly. A token bucket passes the
    'five per second on average' reading of the rule and fails this one."""
    clock = Clock()
    governor = _governor(clock)
    stamps = []
    for _ in range(37):
        governor.acquire()
        stamps.append(clock.now)
        clock.advance(0.001)

    worst = max(sum(1 for t in stamps if start <= t < start + 1.0) for start in stamps)
    assert worst <= 5


def test_a_bucket_style_burst_across_a_boundary_is_prevented() -> None:
    """Five at 0.9s then five at 1.0s would be ten inside 200ms. A refilling
    bucket allows it; a sliding window does not."""
    clock = Clock()
    governor = _governor(clock)
    for _ in range(5):
        governor.acquire()
    clock.advance(0.9)
    assert governor.acquire() > 0.0


def test_non_blocking_mode_refuses_instead_of_waiting() -> None:
    clock = Clock()
    governor = _governor(clock)
    for _ in range(5):
        governor.acquire()
    with pytest.raises(RateLimitExceeded, match="already sent"):
        governor.acquire(block=False)
    assert clock.now == 0.0


def test_a_wait_longer_than_max_wait_is_an_error_not_a_silent_stall() -> None:
    clock = Clock()
    governor = _governor(clock, 1, max_wait=0.5)
    governor.acquire()
    with pytest.raises(RateLimitExceeded, match="too large"):
        governor.acquire()


def test_the_slot_is_spent_even_if_the_send_then_fails() -> None:
    """The exchange counted the message regardless of what it replied, so the
    governor must too."""
    clock = Clock()
    governor = _governor(clock, 2)
    governor.acquire()
    governor.acquire()
    assert governor.recent() == 2


def test_a_zero_limit_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="positive"):
        Governor(0)
