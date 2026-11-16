"""The three live-order gaps the 2026-11-01 audit found (T-4349, T-4350).

T-4348 (Kite's duplicate tags) is tested beside the adapter in
`test_broker_kite.py`. Every OMS here lives in `tmp_path`.
"""

from __future__ import annotations

import json
import multiprocessing
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.backtest.events import Order, client_order_id
from eulerlab.costs.schedule import Side
from eulerlab.oms import ems
from eulerlab.oms.broker import BrokerOrderView, BrokerUnreachable
from eulerlab.oms.journal import Journal
from eulerlab.oms.killswitch import KillSwitch
from eulerlab.oms.oms import OMS
from eulerlab.oms.states import OrderState

DAY = date(2026, 10, 30)


class DailyBook:
    """A broker whose order book, like Kite's, forgets yesterday."""

    name = "dailybook"
    order_book_is_daily = True

    def __init__(self) -> None:
        self.book: dict[str, BrokerOrderView] = {}

    def place(self, order: Order, *, price: float | None = None) -> str:
        raise BrokerUnreachable("socket closed after send")

    def query(self, client_order_id: str) -> BrokerOrderView | None:
        return self.book.get(client_order_id)

    def cancel(self, client_order_id: str) -> None: ...

    def positions(self) -> dict[str, int]:
        return {}

    def open_orders(self) -> list[BrokerOrderView]:
        return []


def _order() -> Order:
    return Order(
        client_order_id=client_order_id("t", DAY, "TCS", 1),
        strategy_id="t",
        signal_day=DAY,
        symbol="TCS",
        side=Side.BUY,
        quantity=5,
    )


def _oms(tmp_path: Path, adapter: DailyBook) -> OMS:
    return OMS(
        adapter,
        journal=Journal(tmp_path / "orders.jsonl"),
        governor=ems.Governor(100),
        kill_switch=KillSwitch(tmp_path / "KILL_SWITCH", tmp_path / "ks.jsonl"),
    )


def _sent_on(tmp_path: Path, day: str) -> None:
    """Rewrite the journal's timestamps as if the order went out on `day`."""
    path = tmp_path / "orders.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    for line in lines:
        line["at"] = f"{day}T05:00:00+00:00"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def test_an_order_from_yesterday_missing_from_a_daily_book_stays_unknown(tmp_path: Path) -> None:
    oms = _oms(tmp_path, DailyBook())
    assert oms.submit(_order()) is OrderState.UNKNOWN
    _sent_on(tmp_path, "2026-10-30")

    report = OMS(
        oms.adapter, journal=Journal(tmp_path / "orders.jsonl"), governor=oms.governor
    ).resolve_unknown(today=date(2026, 10, 31))
    assert report.resolved == {}
    assert report.unresolved == [_order().client_order_id]
    assert "sent on 2026-10-30" in report.breaks[0]


def test_the_same_order_missing_on_the_day_it_was_sent_resolves_as_unsent(tmp_path: Path) -> None:
    oms = _oms(tmp_path, DailyBook())
    oms.submit(_order())
    _sent_on(tmp_path, "2026-10-31")
    report = oms.resolve_unknown(today=date(2026, 10, 31))
    assert report.resolved == {_order().client_order_id: OrderState.UNSENT}


def test_a_broker_that_keeps_history_still_resolves_absence(tmp_path: Path) -> None:
    adapter = DailyBook()
    adapter.order_book_is_daily = False
    oms = _oms(tmp_path, adapter)
    oms.submit(_order())
    _sent_on(tmp_path, "2026-10-30")
    report = oms.resolve_unknown(today=date(2026, 10, 31))
    assert report.resolved == {_order().client_order_id: OrderState.UNSENT}


# --- one window across processes (T-4350) ----------------------------------


def test_two_governors_sharing_a_file_share_one_window(tmp_path: Path) -> None:
    now = [1000.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    window = tmp_path / "window.json"
    a = ems.Governor(5, clock=lambda: now[0], sleep=sleep, window_file=window)
    b = ems.Governor(5, clock=lambda: now[0], sleep=sleep, window_file=window)
    for _ in range(3):
        assert a.acquire() == 0.0
    for _ in range(2):
        assert b.acquire() == 0.0
    # Six in one second would break the rule; the sixth waits, whoever sends it.
    assert b.acquire() == 1.0
    assert slept == [1.0]
    assert a.recent() == 1


def test_a_shared_window_refuses_when_asked_not_to_wait(tmp_path: Path) -> None:
    window = tmp_path / "window.json"
    clock = lambda: 50.0  # noqa: E731
    first = ems.Governor(2, clock=clock, window_file=window)
    first.acquire()
    first.acquire()
    second = ems.Governor(2, clock=clock, window_file=window)
    try:
        second.acquire(block=False)
    except ems.RateLimitExceeded as exc:
        assert "this machine's senders" in str(exc)
    else:
        raise AssertionError("the third send in one second was allowed")


FROZEN_NOW = 1_000_000.0
"""Every child reads this as the time. The lock is under test, not the clock:
on wall-clock time a child that starts more than a second after the first is
allowed a slot because the window has slid, so the test failed under machine
load (6 taken on 2026-11-15) with the limiter working as designed."""


def _claim(path: str, go: Any, out: multiprocessing.Queue) -> None:  # type: ignore[type-arg]
    governor = ems.Governor(
        5, clock=lambda: FROZEN_NOW, window_file=Path(path), sleep=lambda s: None
    )
    go.wait(30)  # start together, so the claims really contend for the lock
    try:
        governor.acquire(block=False)
        out.put(1)
    except ems.RateLimitExceeded:
        out.put(0)


def test_real_processes_cannot_both_take_the_last_slot(tmp_path: Path) -> None:
    """The lock is what makes this hold: eight processes at once, five slots.

    All eight share one frozen instant, so exactly five may succeed however
    slowly the machine starts them.
    """
    window = tmp_path / "window.json"
    go = multiprocessing.Event()
    out: multiprocessing.Queue = multiprocessing.Queue()  # type: ignore[type-arg]
    workers = [
        multiprocessing.Process(target=_claim, args=(str(window), go, out)) for _ in range(8)
    ]
    for worker in workers:
        worker.start()
    go.set()
    taken = sum(out.get(timeout=30) for _ in workers)
    for worker in workers:
        worker.join(timeout=20)
    assert taken == 5


def test_a_slot_frees_only_after_a_full_second(tmp_path: Path) -> None:
    """The legitimate way a sixth order goes through: the window slid. Just
    under a second is still refused; a full second later is allowed."""
    window = tmp_path / "window.json"
    now = [500.0]
    governor = ems.Governor(5, clock=lambda: now[0], window_file=window)
    for _ in range(5):
        governor.acquire(block=False)
    now[0] += 0.999
    try:
        governor.acquire(block=False)
    except ems.RateLimitExceeded:
        pass
    else:
        raise AssertionError("a sixth order inside one second was allowed")
    now[0] += 0.001
    assert governor.acquire(block=False) == 0.0


def test_the_live_governor_uses_the_one_shared_window() -> None:
    assert ems.live_governor().window_file == ems.LIVE_WINDOW
