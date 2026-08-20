"""The kill switch. Trip it from anywhere; clear it only by hand.

`CLAUDE.md`: *Kill switches are implemented in a separate process with
separate credentials from the strategies.*

The asymmetry is the design. **Anything may trip it. Almost nothing may clear
it.** Tripping is cheap and reversible — the cost of a false trip is a day of
not trading. Clearing is the expensive direction, because it re-arms a system
that something just decided was misbehaving, and the decision to do that
belongs to a person who has looked at why.

So:

- `trip()` is importable, callable from the OMS, and needs no credential.
- There is **no clear function in this module's importable surface**. Clearing
  happens in `main()`, behind `--reset`, and requires `KILLSWITCH_TOKEN` —
  a credential the trading path never loads. `tests/test_killswitch.py`
  asserts that no other module under `src/eulerlab` so much as mentions that
  variable, the same structural check that keeps thresholds out of `gates.py`.
- Every trip and every clear appends to a log that is never rewritten, so
  "who turned it back on and why" always has an answer.

**What this is not.** On one machine, with one user account, a determined
process can delete the trip file directly and no amount of Python prevents it.
The separation here is by code structure and by credential, not by operating
system. Real separation means the switch runs as a different user on a
different host, and ideally that the broker itself holds a second API key
whose only power is to square off and disable — so the switch works even when
this machine is the thing that is broken. That is a Sprint 29 item, recorded
in `docs/STUBS.md` (S-019) rather than quietly assumed away.

The automatic limits are the second half. A switch that only a human can trip
is a switch that is not tripped at 2 a.m.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

TRIP_PATH = Path("data/oms/KILL_SWITCH")
TRIP_LOG_PATH = Path("data/oms/killswitch_log.jsonl")
LIMITS_PATH = Path("config/killswitch.yaml")

TOKEN_VAR = "KILLSWITCH_TOKEN"
"""Named once, here. Referenced nowhere else in `src/`, and a test enforces
that — the trading process must not be able to authenticate a reset even by
accident."""


class KillSwitchTripped(RuntimeError):
    """Raised in place of sending an order. Never caught inside the OMS."""


class Limits(BaseModel):
    """Automatic trip conditions.

    Every one is a count or a rupee amount that a human can check by hand
    against the day's activity, deliberately — a limit whose breach cannot be
    confirmed independently is a limit nobody will trust at the moment it
    fires.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_daily_loss: float = Field(default=10_000.0, gt=0)
    max_orders_per_day: int = Field(default=200, gt=0)
    max_consecutive_rejections: int = Field(default=5, gt=0)
    max_position_notional: float = Field(default=500_000.0, gt=0)
    max_unresolved_orders: int = Field(default=3, gt=0)
    """Orders stuck in UNKNOWN. More than a handful means the broker link is
    unhealthy, and continuing to send into an unhealthy link is how one
    ambiguous order becomes twenty."""


def load_limits(path: Path = LIMITS_PATH) -> Limits:
    if not path.exists():
        return Limits()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Limits.model_validate(raw)


@dataclass(frozen=True)
class DayState:
    """What the limits are checked against. Supplied by the caller so this
    module never reaches for data on its own and can be tested exactly."""

    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0
    orders_today: int = 0
    consecutive_rejections: int = 0
    largest_position_notional: float = 0.0
    unresolved_orders: int = 0

    @property
    def total_pnl(self) -> float:
        return self.realised_pnl + self.unrealised_pnl


def breaches(state: DayState, limits: Limits) -> list[str]:
    """Every limit this state violates, in plain English.

    Returns all of them rather than the first. When a system goes wrong it
    usually breaks several limits at once, and the first one alphabetically is
    rarely the informative one.
    """
    found: list[str] = []
    if state.total_pnl < -limits.max_daily_loss:
        found.append(
            f"daily loss {abs(state.total_pnl):,.0f} exceeds limit {limits.max_daily_loss:,.0f}"
        )
    if state.orders_today > limits.max_orders_per_day:
        found.append(f"{state.orders_today} orders today, limit {limits.max_orders_per_day}")
    if state.consecutive_rejections >= limits.max_consecutive_rejections:
        found.append(
            f"{state.consecutive_rejections} rejections in a row, "
            f"limit {limits.max_consecutive_rejections}"
        )
    if state.largest_position_notional > limits.max_position_notional:
        found.append(
            f"position {state.largest_position_notional:,.0f} exceeds "
            f"limit {limits.max_position_notional:,.0f}"
        )
    if state.unresolved_orders > limits.max_unresolved_orders:
        found.append(
            f"{state.unresolved_orders} orders in UNKNOWN, "
            f"limit {limits.max_unresolved_orders} — the broker link is unhealthy"
        )
    return found


class KillSwitch:
    """Presence of the trip file means stop. That is the entire protocol.

    A file rather than a flag in a database or a field on an object, because
    the switch has to be readable and settable by a process that shares
    nothing else with the trading system — including, on a bad day, by a human
    with a shell and no working application.
    """

    def __init__(self, path: Path = TRIP_PATH, log_path: Path = TRIP_LOG_PATH) -> None:
        self.path = path
        self.log_path = log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def is_tripped(self) -> bool:
        return self.path.exists()

    def reason(self) -> str:
        if not self.is_tripped():
            return ""
        try:
            return str(json.loads(self.path.read_text(encoding="utf-8")).get("reason", ""))
        except (json.JSONDecodeError, OSError):
            # A trip file we cannot parse is still a trip file. Failing to
            # read it must never read as "not tripped".
            return "unreadable trip file"

    def _log(self, action: str, reason: str, by: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"at": datetime.now(UTC).isoformat(), "action": action, "reason": reason, "by": by},
            sort_keys=True,
        )
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def trip(self, reason: str, *, by: str = "system") -> None:
        """Stop trading. Idempotent, and it never overwrites the first reason.

        The first trip is the informative one — everything after it is a
        consequence. Overwriting would replace "daily loss limit" with
        "5 rejections in a row", which is the symptom of already having
        stopped.
        """
        self._log("trip", reason, by)
        if self.is_tripped():
            return
        payload = {"at": datetime.now(UTC).isoformat(), "reason": reason, "by": by}
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())

    def require_clear(self) -> None:
        """Called before every send. Raises rather than returning a bool.

        A boolean gets ignored. An exception does not.
        """
        if self.is_tripped():
            msg = (
                f"KILL SWITCH TRIPPED: {self.reason()}\n"
                f"No order will be sent. Clear it deliberately:\n"
                f"  {TOKEN_VAR}=... uv run python -m eulerlab.oms.killswitch --reset"
            )
            raise KillSwitchTripped(msg)

    def check(self, state: DayState, limits: Limits | None = None) -> list[str]:
        """Evaluate the automatic limits and trip if any is breached."""
        found = breaches(state, limits or load_limits())
        if found:
            self.trip("; ".join(found), by="limits")
        return found


def _reset(switch: KillSwitch, note: str) -> int:
    """Behind `--reset` only, and never importable as a plain function.

    Deliberately awkward. There is no `switch.reset()` because the moment one
    exists, something will call it in a retry loop at three in the morning.
    """
    from eulerlab.env import require

    token = require(TOKEN_VAR)
    if len(token) < 8:
        print(f"{TOKEN_VAR} is too short to be a credential", file=sys.stderr)
        return 2
    if not switch.is_tripped():
        print("kill switch is not tripped; nothing to do")
        return 0
    reason = switch.reason()
    switch._log("reset", note or "(no note given)", by="operator")
    switch.path.unlink()
    print(f"kill switch CLEARED.\n  was: {reason}\n  note: {note or '(none)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The kill switch. Separate from the OMS.")
    parser.add_argument("--status", action="store_true", help="is it tripped, and why")
    parser.add_argument("--trip", metavar="REASON", help="stop trading now")
    parser.add_argument("--reset", action="store_true", help=f"clear it; needs {TOKEN_VAR}")
    parser.add_argument("--note", default="", help="why you are clearing it")
    args = parser.parse_args(argv)

    switch = KillSwitch()
    if args.trip:
        switch.trip(args.trip, by="operator")
        print(f"kill switch TRIPPED: {args.trip}")
        return 0
    if args.reset:
        return _reset(switch, args.note)

    if switch.is_tripped():
        print(f"kill switch: TRIPPED\n  reason: {switch.reason()}")
        print(f"\nclear with: {TOKEN_VAR}=... uv run python -m eulerlab.oms.killswitch --reset")
        return 1
    limits = load_limits()
    print("kill switch: clear")
    print(f"  daily loss limit      {limits.max_daily_loss:,.0f}")
    print(f"  orders per day        {limits.max_orders_per_day}")
    print(f"  consecutive rejects   {limits.max_consecutive_rejections}")
    print(f"  position notional     {limits.max_position_notional:,.0f}")
    print(f"  unresolved orders     {limits.max_unresolved_orders}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
