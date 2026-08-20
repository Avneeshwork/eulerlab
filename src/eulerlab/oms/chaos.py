"""`make chaos` — break it on purpose and check it tells the truth afterwards.

The build plan's verification for the OMS sprints is one line: *chaos tests:
kill process mid-order, pull network.* This is that, and it is deliberately
not a unit-test file. Two of these scenarios `SIGKILL` a real subprocess in the
middle of a real order and then ask a fresh process to work out what happened
from the files left on disk. Nothing is mocked, because the thing being tested
is what survives a process that did not get to finish.

Each scenario runs in its own temporary directory with its own journal, its
own paper-broker state, and — importantly — its own kill-switch file. A chaos
run must never be able to trip the real switch or write to the real journal.

What each scenario is really asking:

| scenario | the question |
|---|---|
| killed before the send | do we invent a position that was never placed? |
| killed after the send | do we lose a position that *was* placed? |
| ambiguous send | do we guess, or do we go and ask? |
| lost send | same event at the call site, opposite truth — do we tell them apart? |
| retry | does sending twice send twice? |
| broker down | does an unanswerable question get answered anyway? |
| rate limit | is the governor a real bound or an average? |
| kill switch | does tripped mean tripped? |
| out-of-band position | do we notice risk we did not create? |
| corrupt journal | does a damaged record read as an empty one? |

The last is the quiet one. A journal that returns "no orders" when it is
actually unreadable is worse than one that crashes, because everything
downstream believes it.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eulerlab.backtest.events import Order, client_order_id
from eulerlab.costs.schedule import Side
from eulerlab.oms import chaos_child, ems, reconcile
from eulerlab.oms.journal import CorruptJournal, Journal
from eulerlab.oms.killswitch import KillSwitch, KillSwitchTripped
from eulerlab.oms.oms import OMS
from eulerlab.oms.paper_broker import PaperBroker, PaperFaults
from eulerlab.oms.states import OrderState

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass(frozen=True)
class ChaosResult:
    name: str
    passed: bool
    detail: str


class Failed(AssertionError):
    """A scenario's expectation did not hold. Carries the explanation."""


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise Failed(message)


def _oms(
    root: Path, *, faults: PaperFaults | None = None, governor: ems.Governor | None = None
) -> OMS:
    """An OMS wired entirely inside `root`. Nothing global is reachable."""
    return OMS(
        PaperBroker(root / "paper_broker.json", faults=faults),
        journal=Journal(root / "orders.jsonl"),
        governor=governor or ems.Governor(5),
        kill_switch=KillSwitch(root / "KILL_SWITCH", root / "killswitch_log.jsonl"),
    )


def _broker_orders(root: Path) -> dict[str, object]:
    """What the paper broker has on disk, read as a stranger would.

    Read from the file rather than through `PaperBroker`, so a scenario
    checking "did anything reach the broker" is not asking the same object it
    is testing.
    """
    path = root / "paper_broker.json"
    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")).get("orders") or {})


def _order(symbol: str = "RELIANCE", seq: int = 1, quantity: int = 10) -> Order:
    from datetime import date

    day = date(2026, 8, 20)
    return Order(
        client_order_id=client_order_id("chaos", day, symbol, seq),
        strategy_id="chaos",
        signal_day=day,
        symbol=symbol,
        side=Side.BUY,
        quantity=quantity,
    )


def _run_child(mode: str, root: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "eulerlab.oms.chaos_child", "--mode", mode, "--dir", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    expect(
        completed.returncode == -signal.SIGKILL,
        f"the child was supposed to be SIGKILLed, exited {completed.returncode} instead. "
        f"stderr: {completed.stderr.strip()[:300]}",
    )


# --- scenarios --------------------------------------------------------------


def killed_before_the_send(root: Path) -> str:
    _run_child("after-intent", root)
    oms = _oms(root)
    expect(
        oms.states()[chaos_child.the_order().client_order_id] is OrderState.INTENT,
        "the journal should still say INTENT — the child died before sending",
    )
    report = oms.recover()
    state = oms.states()[chaos_child.the_order().client_order_id]
    expect(state is OrderState.UNSENT, f"expected UNSENT after recovery, got {state.value}")
    expect(not oms.executions(), "recovery invented a fill for an order never sent")
    expect(report.clean, f"recovery should be clean: {report.breaks}")
    return "child SIGKILLed between journal and send; recovered to UNSENT, no phantom position"


def killed_after_the_send(root: Path) -> str:
    _run_child("after-place", root)
    coid = chaos_child.the_order().client_order_id
    oms = _oms(root)
    expect(
        oms.states()[coid] is OrderState.INTENT,
        "the journal should still say INTENT — the child died before recording the reply",
    )
    oms.recover()
    state = oms.states()[coid]
    expect(state is OrderState.FILLED, f"expected FILLED after recovery, got {state.value}")
    executions = oms.executions()
    expect(len(executions) == 1, f"expected 1 execution, got {len(executions)}")
    expect(
        executions[0].price == chaos_child.PRICE,
        f"fill price {executions[0].price} is not the broker's {chaos_child.PRICE}",
    )
    return "child SIGKILLed between send and record; the live order was found and adopted"


def ambiguous_send_is_resolved_by_asking(root: Path) -> str:
    oms = _oms(root, faults=PaperFaults(unreachable_on_place=1))
    order = _order()
    state = oms.submit(order, price=100.0)
    expect(state is OrderState.UNKNOWN, f"a timeout must give UNKNOWN, got {state.value}")
    report = oms.resolve_unknown()
    expect(
        oms.states()[order.client_order_id] is OrderState.FILLED,
        "the order was live at the broker; the query should have found it",
    )
    expect(report.clean, "resolution should be clean")
    return "timeout on a send that did land: UNKNOWN, then resolved to FILLED by query"


def lost_send_is_resolved_by_asking(root: Path) -> str:
    oms = _oms(root, faults=PaperFaults(lost_on_place=1))
    order = _order()
    state = oms.submit(order, price=100.0)
    expect(state is OrderState.UNKNOWN, f"a reset must give UNKNOWN, got {state.value}")
    oms.resolve_unknown()
    expect(
        oms.states()[order.client_order_id] is OrderState.UNSENT,
        "the order never reached the broker; the query should have said so",
    )
    expect(not oms.executions(), "an unsent order produced a fill")
    return "connection reset on a send that did not land: UNKNOWN, then UNSENT — same event, opposite truth"


def retry_cannot_double_send(root: Path) -> str:
    oms = _oms(root)
    order = _order()
    first = oms.submit(order, price=100.0)
    second = oms.submit(order, price=100.0)
    expect(
        first is OrderState.FILLED and second is OrderState.FILLED,
        "both submits should report FILLED",
    )
    at_broker = _broker_orders(root)
    expect(
        len(at_broker) == 1,
        f"the broker holds {len(at_broker)} orders; a retry double-sent",
    )
    expect(len(oms.executions()) == 1, "the retry produced a second fill")
    return "the same order submitted twice reached the broker once"


def broker_down_leaves_it_unknown(root: Path) -> str:
    oms = _oms(root, faults=PaperFaults(unreachable_on_place=1, unreachable_on_query=5))
    order = _order()
    oms.submit(order, price=100.0)
    for _ in range(3):
        report = oms.resolve_unknown()
    expect(
        oms.states()[order.client_order_id] is OrderState.UNKNOWN,
        "an unanswerable query must leave the order UNKNOWN, not guess",
    )
    expect(report.unresolved == [order.client_order_id], "the order should be reported unresolved")
    expect(not report.resolved, "nothing was resolved and nothing should claim to be")
    return "three failed queries in a row: still UNKNOWN, never assumed"


def rate_limit_is_a_hard_bound(root: Path) -> str:
    now = [0.0]
    stamps: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    governor = ems.Governor(5, clock=clock, sleep=sleep)
    oms = _oms(root, governor=governor)
    for seq in range(20):
        oms.submit(_order(symbol=f"SYM{seq:02d}", seq=seq), price=100.0)
        stamps.append(now[0])
        now[0] += 0.001  # sending is not instantaneous

    worst = max(sum(1 for t in stamps if start <= t < start + 1.0) for start in stamps)
    expect(worst <= 5, f"{worst} orders landed inside one second, limit is 5")
    return f"20 orders at 5/s: worst one-second window held {worst}, took {now[0]:.2f}s"


def a_tripped_switch_stops_everything(root: Path) -> str:
    oms = _oms(root)
    oms.kill_switch.trip("chaos test", by="test")
    order = _order()
    try:
        oms.submit(order, price=100.0)
    except KillSwitchTripped:
        pass
    else:
        raise Failed("submit went through with the kill switch tripped")

    expect(
        oms.states()[order.client_order_id] is OrderState.UNSENT,
        "a refused order must be recorded as UNSENT, not forgotten",
    )
    # The broker's state file does not exist at all: PaperBroker only writes
    # when it accepts something. Absence is the strongest form of "nothing was
    # sent", so treat it as the empty case rather than as a missing file.
    expect(
        not _broker_orders(root),
        "an order reached the broker with the switch tripped",
    )
    # A fresh process must find it still tripped. A switch that only lives in
    # the memory of the process it stopped is not a kill switch.
    restarted = _oms(root)
    try:
        restarted.submit(_order(symbol="TCS", seq=2), price=100.0)
    except KillSwitchTripped:
        pass
    else:
        raise Failed("a restart cleared the kill switch")
    return "tripped: submit raised, nothing sent, and a restart did not clear it"


def an_out_of_band_position_is_noticed(root: Path) -> str:
    oms = _oms(root)
    oms.submit(_order(symbol="TCS", seq=1), price=100.0)
    broker = PaperBroker(root / "paper_broker.json")
    broker.inject("manual-trade-in-the-app", "INFY", Side.BUY, 40, 1500.0)

    result = reconcile.reconcile(oms, broker)
    expect(not result.clean, "the reconciler saw nothing wrong")
    kinds = {b.kind for b in result.breaks}
    expect("broker_only" in kinds, f"expected a broker_only break, got {kinds}")
    infy = next(b for b in result.breaks if b.symbol == "INFY")
    expect(infy.broker == 40 and infy.local == 0, f"break reported wrongly: {infy}")
    return "a position created outside the OMS was found: INFY 40 at the broker, 0 locally"


def a_damaged_journal_refuses_to_load(root: Path) -> str:
    path = root / "orders.jsonl"
    oms = _oms(root)
    for seq in range(1, 4):
        oms.submit(_order(symbol=f"SYM{seq}", seq=seq), price=100.0)
    lines = path.read_text(encoding="utf-8").splitlines()
    expect(len(lines) >= 4, "not enough events to corrupt one in the middle")

    lines[1] = "{ this is not json"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        Journal(path).read()
    except CorruptJournal:
        pass
    else:
        raise Failed("a corrupt line in the middle of the journal was read as if fine")
    return "a mangled line mid-file raises; it never reads as an empty journal"


def a_torn_last_line_is_tolerated(root: Path) -> str:
    path = root / "orders.jsonl"
    oms = _oms(root)
    for seq in range(1, 4):
        oms.submit(_order(symbol=f"SYM{seq}", seq=seq), price=100.0)
    before = len(Journal(path).read())

    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 99, "at": "2026-08-2')  # power cut, mid-write
    after = len(Journal(path).read())
    expect(after == before, f"a torn tail changed the event count from {before} to {after}")
    return f"a half-written final line is discarded; {before} complete events still read"


SCENARIOS: tuple[tuple[str, Callable[[Path], str]], ...] = (
    ("killed before the send", killed_before_the_send),
    ("killed after the send", killed_after_the_send),
    ("ambiguous send", ambiguous_send_is_resolved_by_asking),
    ("lost send", lost_send_is_resolved_by_asking),
    ("retry", retry_cannot_double_send),
    ("broker unreachable", broker_down_leaves_it_unknown),
    ("rate limit", rate_limit_is_a_hard_bound),
    ("kill switch", a_tripped_switch_stops_everything),
    ("out-of-band position", an_out_of_band_position_is_noticed),
    ("corrupt journal", a_damaged_journal_refuses_to_load),
    ("torn last line", a_torn_last_line_is_tolerated),
)


def run_all() -> list[ChaosResult]:
    results: list[ChaosResult] = []
    for name, scenario in SCENARIOS:
        with tempfile.TemporaryDirectory(prefix="eulerlab-chaos-") as tmp:
            try:
                detail = scenario(Path(tmp))
            except Failed as exc:
                results.append(ChaosResult(name, False, str(exc)))
            except Exception as exc:
                results.append(ChaosResult(name, False, f"{type(exc).__name__}: {exc}"))
            else:
                results.append(ChaosResult(name, True, detail))
    return results


def main() -> int:
    import os

    colour = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def paint(text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if colour else text

    print(paint(f"\n{'SCENARIO':<24}{'RESULT':<8}{'WHAT HAPPENED'}", DIM))
    results = run_all()
    for result in results:
        label = "PASS" if result.passed else "FAIL"
        print(
            f"{result.name:<24}{paint(f'{label:<8}', GREEN if result.passed else RED)}{result.detail}"
        )

    failures = [r for r in results if not r.passed]
    if failures:
        print(paint(f"\nchaos FAILED: {len(failures)} of {len(results)} scenarios red", RED))
        return 1
    print(paint(f"\nchaos OK: all {len(results)} scenarios survived", GREEN))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
