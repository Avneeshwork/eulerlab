"""The rate governor: a bound, not an average.

Every test here drives a fake clock. A governor tested against wall-clock time
gets tested loosely — nobody writes a test that sleeps for four seconds — and
loosely tested is how a limit becomes an average.
"""

from __future__ import annotations

import time

import pytest

from eulerlab.config import load_execution
from eulerlab.oms.ems import Governor, RateLimitExceeded, SimulatedClock


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


def _governor(clock: Clock, limit: int = 5, **kwargs: float) -> Governor:
    return Governor(limit, clock=clock, sleep=clock.sleep, **kwargs)


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


def _worst_second(stamps: list[float]) -> int:
    """The most sends inside any half-open one-second window."""
    worst, first = 0, 0
    for last, stamp in enumerate(stamps):
        while stamp - stamps[first] >= 1.0:
            first += 1
        worst = max(worst, last - first + 1)
    return worst


def test_a_simulated_governor_holds_the_limit_without_sleeping() -> None:
    """Paper and deploy runs (ADR-061): the same window and the same waits,
    without spending real seconds in front of a broker that counts nothing."""
    governor = Governor.simulated(5)
    stamps = []
    started = time.monotonic()
    for _ in range(50):
        governor.acquire()
        stamps.append(governor._sends[-1])  # the time the slot was claimed at
    assert time.monotonic() - started < 1.0, "a simulated wait must not block"
    assert governor.total_waited >= 8.9, "fifty sends at five a second wait about nine"
    assert _worst_second(stamps) <= 5


@pytest.mark.parametrize("stuck_at", [0.0, 0.1, 1000.0, 123456.789, 3.7e6])
def test_the_simulated_clock_holds_the_limit_when_real_time_stands_still(
    stuck_at: float,
) -> None:
    """Without the overshoot a real sleep always has, a clock landing exactly
    on the window edge could round to just inside it; at 0.1 the limit then
    stopped holding entirely."""
    clock = SimulatedClock(clock=lambda: stuck_at)
    governor = Governor(5, clock=clock, sleep=clock.sleep)
    stamps = []
    for _ in range(2000):
        governor.acquire()
        stamps.append(governor._sends[-1])
    assert _worst_second(stamps) <= 5
    assert governor.recent() <= 5
