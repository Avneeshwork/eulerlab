"""`make check-costs` — the acceptance gate for the cost model.

The build plan's criterion is *"reproduces 20 of your real contract notes to
the paisa"*. Real contract notes are the only thing that can settle whether
this model is right, because every rate in it comes from secondary sources —
NSE's own pages and the CBDT circular would not fetch (A-016).

So this gate is built to consume them and reports **PARTIAL** until it has
them, naming exactly what is missing. It does not substitute a synthetic
figure and call itself passed: a cost model validated against numbers I
invented would be worse than none, because it would look verified.

What it *can* check without them, and does: the published worked example for
option exercise, the internal consistency of every line, and that the sides
and time-versioning behave as documented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from eulerlab.costs.model import cost_of_exercise, cost_of_trade
from eulerlab.costs.schedule import Segment, Side

NOTES_PATH = Path("config/contract_notes.json")
EXAMPLE_PATH = Path("config/contract_notes.example.json")
TOLERANCE = Decimal("0.01")
REQUIRED_NOTES = 20


@dataclass
class Result:
    name: str
    status: str
    detail: str

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"


def _ok(n: str, d: str) -> Result:
    return Result(n, "PASS", d)


def _fail(n: str, d: str) -> Result:
    return Result(n, "FAIL", d)


def _partial(n: str, d: str) -> Result:
    return Result(n, "PARTIAL", d)


def check_published_example() -> Result:
    """The one figure with a published answer: Zerodha's exercise example."""
    cost = cost_of_exercise(
        trade_date=date(2026, 8, 1),
        settlement_price=Decimal("17350"),
        strike=Decimal("17300"),
        quantity=50,
    )
    if cost.stt != Decimal("3.75"):
        return _fail("published example", f"exercise STT is {cost.stt}, expected 3.75")
    return _ok("published example", "exercise STT Rs 3.75 on Rs 2,500 intrinsic, as published")


def check_stt_trap_is_modelled() -> Result:
    """The pre-2019 notional rule must still be reachable, because it applies
    to the first four and a half years of our own price history."""
    old = cost_of_exercise(
        trade_date=date(2018, 6, 1),
        settlement_price=Decimal("17350"),
        strike=Decimal("17300"),
        quantity=50,
    )
    new = cost_of_exercise(
        trade_date=date(2026, 8, 1),
        settlement_price=Decimal("17350"),
        strike=Decimal("17300"),
        quantity=50,
    )
    if old.stt <= new.stt * 50:
        return _fail("STT trap", f"pre-2019 STT {old.stt} is not materially above {new.stt}")
    return _ok("STT trap", f"pre-2019 Rs {old.stt} vs post-2019 Rs {new.stt} on the same expiry")


def check_sides() -> Result:
    """Each charge on the leg that actually bears it."""
    common = dict(trade_date=date(2026, 8, 1), price=Decimal("1000"), quantity=100)
    intraday_buy = cost_of_trade(segment=Segment.EQUITY_INTRADAY, side=Side.BUY, **common)  # type: ignore[arg-type]
    intraday_sell = cost_of_trade(segment=Segment.EQUITY_INTRADAY, side=Side.SELL, **common)  # type: ignore[arg-type]
    delivery_sell = cost_of_trade(segment=Segment.EQUITY_DELIVERY, side=Side.SELL, **common)  # type: ignore[arg-type]

    problems = []
    if intraday_buy.stt != 0:
        problems.append("intraday buy paid STT")
    if intraday_sell.stt == 0:
        problems.append("intraday sell paid no STT")
    if delivery_sell.stamp_duty != 0:
        problems.append("a sell paid stamp duty")
    if problems:
        return _fail("charge sides", "; ".join(problems))
    return _ok("charge sides", "STT sell-side for intraday/futures, stamp duty buy-side only")


def check_gst_base() -> Result:
    """GST on fees, never on turnover."""
    cost = cost_of_trade(
        trade_date=date(2026, 8, 1),
        segment=Segment.EQUITY_INTRADAY,
        side=Side.SELL,
        price=Decimal("1000"),
        quantity=100,
    )
    expected = (cost.brokerage + cost.exchange_txn) * Decimal("0.18")
    if abs(cost.gst - expected) > TOLERANCE:
        return _fail("GST base", f"GST {cost.gst} is not 18% of brokerage+txn ({expected})")
    return _ok("GST base", f"Rs {cost.gst} = 18% of brokerage plus transaction charges")


def check_contract_notes(path: Path = NOTES_PATH) -> Result:
    """The real gate. Compares every line against a real note, to the paisa."""
    name = "contract notes"
    if not path.exists():
        return _partial(
            name,
            f"no {path}. Copy {EXAMPLE_PATH} and fill in real figures - "
            f"{REQUIRED_NOTES} notes are needed to pass",
        )

    notes = json.loads(path.read_text(encoding="utf-8"))
    real = [n for n in notes if not str(n.get("note_id", "")).startswith("example")]
    if not real:
        return _partial(name, f"{path} holds only the example row; real notes are needed")

    mismatches: list[str] = []
    for note in real:
        cost = cost_of_trade(
            trade_date=date.fromisoformat(note["trade_date"]),
            segment=Segment(note["segment"]),
            side=Side(note["side"]),
            price=Decimal(note["price"]),
            quantity=int(note["quantity"]),
        )
        actual = note["actual"]
        for label, modelled in cost.lines():
            key = label.lower().replace(" ", "_").replace("stt", "stt")
            expected_raw = actual.get(key)
            if expected_raw is None:
                continue
            expected = Decimal(str(expected_raw))
            if abs(modelled - expected) > TOLERANCE:
                mismatches.append(f"{note['note_id']} {label}: model {modelled} vs note {expected}")

    if mismatches:
        return _fail(name, f"{len(mismatches)} line(s) differ: " + "; ".join(mismatches[:3]))
    if len(real) < REQUIRED_NOTES:
        return _partial(
            name,
            f"{len(real)} of {REQUIRED_NOTES} notes match to the paisa - correct so far, "
            f"but the gate needs {REQUIRED_NOTES}",
        )
    return _ok(name, f"all {len(real)} notes reproduced to the paisa")


CHECKS = (
    check_published_example,
    check_stt_trap_is_modelled,
    check_sides,
    check_gst_base,
)


def main() -> int:
    results = [check() for check in CHECKS]
    results.append(check_contract_notes())

    width = max(len(r.name) for r in results)
    print(f"\n{'CHECK'.ljust(width)}  RESULT   DETAIL")
    for r in results:
        print(f"{r.name.ljust(width)}  {r.status:<7}  {r.detail}")

    failed = [r for r in results if r.failed]
    partial = [r for r in results if r.status == "PARTIAL"]
    print()
    if failed:
        print(f"check-costs FAILED: {len(failed)} of {len(results)} red")
        return 1
    if partial:
        print(
            f"check-costs PARTIAL: {len(results) - len(partial)} green, {len(partial)} "
            f"awaiting real contract notes.\n"
            f"The model is internally consistent and matches the one published example,\n"
            f"but every rate in it comes from secondary sources (A-016). Only your own\n"
            f"notes can settle whether it is right."
        )
        return 0
    print(f"check-costs OK: {len(results)} checks green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
