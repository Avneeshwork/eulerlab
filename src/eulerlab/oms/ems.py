"""The execution side: the rate governor, and the one place a send happens.

`CLAUDE.md`: *EMS enforces `max_orders_per_second` from config, default 5.*

**A sliding window, not a token bucket.** The two are usually
interchangeable; here they are not. A token bucket that refills 5 tokens each
second permits 5 sends at 0.99s and 5 more at 1.01s — ten orders inside a
200-millisecond span, which is precisely the burst a regulator counting orders
per second would see and object to. The rule is written as "in any one-second
window", so the implementation tracks a one-second window. The cost is a
handful of timestamps in memory.

**The clock is injected.** Tests must be able to prove the limit holds without
sleeping through real seconds, and a governor that is only ever tested against
wall-clock time gets tested loosely or not at all.

**Waiting is the default; refusing is available.** Blocking is right for a
rebalance, where the orders all need to go and the only question is how fast.
`max_wait` exists because a send queue that silently blocks for a minute is
its own kind of failure — at some point the honest answer is to stop and say
the plan is too large for the rate limit.

The `send` function is the only place in this project that calls a broker's
`place`. Everything about classifying what happened — landed, definitely
refused, or unknown — is decided once, here, so no caller has to remember that
a timeout is not a rejection.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from eulerlab.backtest.events import Order
from eulerlab.config import load_execution
from eulerlab.oms.broker import (
    BrokerAdapter,
    BrokerRejected,
    BrokerUnreachable,
    DuplicateOrder,
)
from eulerlab.oms.states import Event

WINDOW_SECONDS = 1.0


class RateLimitExceeded(RuntimeError):
    """The governor refused rather than waited. Only raised when asked to."""


class Governor:
    """At most `max_per_second` sends in any one-second window."""

    def __init__(
        self,
        max_per_second: int | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_wait: float = 30.0,
    ) -> None:
        self.max_per_second = (
            max_per_second if max_per_second is not None else load_execution().max_orders_per_second
        )
        if self.max_per_second <= 0:
            msg = "max_orders_per_second must be positive"
            raise ValueError(msg)
        self._clock = clock
        self._sleep = sleep
        self.max_wait = max_wait
        self._sends: deque[float] = deque()
        self.total_waited = 0.0

    def _purge(self, now: float) -> None:
        while self._sends and now - self._sends[0] >= WINDOW_SECONDS:
            self._sends.popleft()

    def recent(self) -> int:
        """Sends inside the current window. For reporting, not for deciding."""
        self._purge(self._clock())
        return len(self._sends)

    def acquire(self, *, block: bool = True) -> float:
        """Claim one slot. Returns the seconds spent waiting.

        Claims the slot *before* the send rather than after. If the send then
        fails, the slot is still spent — which is correct: the exchange
        counted the message regardless of what it replied.
        """
        now = self._clock()
        self._purge(now)
        if len(self._sends) < self.max_per_second:
            self._sends.append(now)
            return 0.0

        wait = WINDOW_SECONDS - (now - self._sends[0])
        if not block:
            msg = (
                f"{self.max_per_second} orders already sent in the last second; "
                f"a slot frees in {wait:.3f}s"
            )
            raise RateLimitExceeded(msg)
        if wait > self.max_wait:
            msg = (
                f"would have to wait {wait:.1f}s for a slot, limit {self.max_wait:.1f}s. "
                f"The order plan is too large for {self.max_per_second} orders/second."
            )
            raise RateLimitExceeded(msg)

        self._sleep(wait)
        self.total_waited += wait
        now = self._clock()
        self._purge(now)
        self._sends.append(now)
        return wait


@dataclass(frozen=True)
class SendOutcome:
    """What the broker did, translated once into the state machine's language."""

    event: Event
    broker_order_id: str = ""
    detail: str = ""

    @property
    def landed(self) -> bool:
        return self.event is Event.SEND_OK


def send(adapter: BrokerAdapter, order: Order, *, price: float | None = None) -> SendOutcome:
    """Place one order and classify the result. The only call site of `place`.

    The `DuplicateOrder` branch is the payoff for deterministic client order
    ids. A retry of an order the broker already has produces a rejection that
    means *the original is fine*, so it resolves to `SEND_OK` rather than to a
    failure — the intention succeeded, just not on this attempt. Treating it as
    an error would send the caller into a retry loop against a broker that is
    already doing the right thing.
    """
    try:
        broker_order_id = adapter.place(order, price=price)
    except DuplicateOrder as exc:
        return SendOutcome(Event.SEND_OK, detail=f"already at broker: {exc}")
    except BrokerRejected as exc:
        return SendOutcome(Event.REJECT, detail=str(exc))
    except BrokerUnreachable as exc:
        # The dangerous one. It may be resting at the exchange right now.
        return SendOutcome(Event.SEND_AMBIGUOUS, detail=str(exc))
    return SendOutcome(Event.SEND_OK, broker_order_id=broker_order_id)
