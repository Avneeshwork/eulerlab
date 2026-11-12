"""The dead-man switch: trip the kill switch when the live book's clock goes quiet.

The live-money book (`deploy/live_money.py`) is driven by a thread inside the
API process that ticks every 20 seconds and writes `live_money/heartbeat.json`
each time. If that process dies, sleeps or hangs with an MIS position open,
nothing exits the position at 15:10 and nothing watches the loss cap. Until
now the only backstop was the broker's own square-off.

This runs **in the kill-switch process, not the trading process** (CLAUDE.md:
kill switches live apart from the strategies). It reads two small files and
never imports the book, the broker or a credential. During market hours on a
session the book is armed for, a heartbeat older than `STALE` trips the kill
switch and sends one message. It trips once per session; clearing is the
operator's, as for every trip (`killswitch.py`).

What it cannot do, said plainly: trip does not square off. The process that
could send the exit order is the one that went quiet (S-019). The message
therefore says to square off by hand, and the broker's auto square-off from
15:12 remains the last line. A broker-side stop placed at entry is the real
fix and is issue #125.

Usage
  uv run python -m eulerlab.oms.deadman          watch until stopped
  uv run python -m eulerlab.oms.deadman --check  one look, print the verdict, exit
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab import notify
from eulerlab.oms.killswitch import KillSwitch
from eulerlab.paths import data_path

IST = ZoneInfo("Asia/Kolkata")
STALE = timedelta(seconds=120)
"""Six missed 20-second ticks. One or two happen on a slow broker call."""
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
EVERY = 30.0


def book_dir() -> Path:
    return data_path("live_money")


def state_path() -> Path:
    return data_path("oms/deadman.json")


def _read(path: Path) -> dict[str, Any]:
    try:
        return dict(json.loads(path.read_text()))
    except (OSError, ValueError):
        return {}


@dataclass(frozen=True)
class Verdict:
    armed: bool
    in_hours: bool
    heartbeat_age_s: int | None
    stale: bool
    tripped: bool
    why: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def check(
    now: datetime | None = None,
    *,
    switch: KillSwitch | None = None,
    send: Callable[[str], Any] = notify.send,
) -> Verdict:
    """One look. Trips the switch when the armed book's clock is stale in market hours."""
    now = now or datetime.now(IST)
    today = now.date()
    deploy = _read(book_dir() / "deploy.json")
    armed = deploy.get("status") == "armed" and deploy.get("for_session") == today.isoformat()
    in_hours = now.isoweekday() <= 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE
    beat = _read(book_dir() / "heartbeat.json")
    age: int | None = None
    if beat.get("at"):
        try:
            at = datetime.fromisoformat(str(beat["at"]))
            if at.tzinfo is None:
                at = at.replace(tzinfo=IST)
            age = int((now - at).total_seconds())
        except ValueError:
            age = None
    stale = age is None or age > STALE.total_seconds()
    if not (armed and in_hours):
        return Verdict(armed, in_hours, age, stale, False, "nothing armed in market hours")
    if not stale:
        return Verdict(armed, in_hours, age, stale, False, f"clock alive, {age}s ago")
    state = _read(state_path())
    if state.get("tripped_for") == today.isoformat():
        return Verdict(armed, in_hours, age, stale, True, "already tripped today")
    switch = switch or KillSwitch(
        data_path("oms/KILL_SWITCH"), data_path("oms/killswitch_log.jsonl")
    )
    why = (
        f"dead-man: the live book is armed for {today} but its clock last ticked "
        f"{'never' if age is None else f'{age}s ago'}. Positions may be open: square off by hand."
    )
    switch.trip(why, by="deadman")
    state_path().parent.mkdir(parents=True, exist_ok=True)
    state_path().write_text(
        json.dumps({"tripped_for": today.isoformat(), "at": now.isoformat(timespec="seconds")})
        + "\n"
    )
    send(f"KILL SWITCH TRIPPED. {why}")
    return Verdict(armed, in_hours, age, stale, True, why)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="one look, then exit")
    parser.add_argument("--every", type=float, default=EVERY)
    args = parser.parse_args(argv)
    if args.check:
        print(json.dumps(check().as_dict(), indent=2))
        return 0
    print(f"deadman: watching {book_dir()} every {args.every:g}s, stale after {STALE}")
    while True:
        try:
            verdict = check()
            if verdict.tripped:
                print(verdict.why)
        except Exception as exc:  # the watcher must outlive one bad look
            print(f"deadman: {type(exc).__name__}: {exc}", file=sys.stderr)
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
