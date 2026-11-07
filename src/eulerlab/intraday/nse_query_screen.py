"""Fade a stock's move after NSE queries it (research 167, H-0107 to H-0110).

NSE asks a company to explain an unusual move ("Spurt in Volume", "Price
movement") or a news report ("News Verification") and posts the reply in
`nse_announcements`, timed by `exchdisstime`. Pre-registered before any run:

- **H-0107** volume or price query posted outside hours: fade the 3-session
  move (>= 3%) on the next session, 09:20 to 15:10.
- **H-0108** news verification posted outside hours: fade the last session's
  move (>= 2%) on the next session, 09:20 to 15:10.
- **H-0109 / H-0110** the same queries posted 09:20 to 14:30: fade the move
  since the previous close (>= 3% / >= 2%) from the open after the next
  5-minute close to 15:10.

Fills come from research 161's snapshots (`make minute-six`): ₹1 lakh a
position, 1x, at most ten a day (largest move first), cash intraday charges
plus 2 bps a side, 2021-08-20 to 2024-11-29. `make nse-queries` writes
`data/derived/nse_queries_intraday.json`.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from eulerlab.validation.intraday import IntradayRun

from eulerlab.intraday import cash_five_screen as five
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import minute_six_screen as six
from eulerlab.intraday import stock_fo_screen as fo

IST = ZoneInfo("Asia/Kolkata")
OUT = Path("data/derived/nse_queries_intraday.json")
EVENTS = Path("data/derived/nse_query_events.json")
SPURT = ("Spurt in Volume", "Price movement")
NEWS = ("News Verification",)
OPEN_MINUTES = 0
"""09:15, as minutes after 09:15."""
LAST_IN_HOURS = 315
"""14:30: the latest in-hours dissemination traded the same day."""
CLOSED_AFTER = 375
"""15:30: a reply posted at or after this is traded on the next session."""
LATE = 5


@dataclass(frozen=True)
class Event:
    symbol: str
    kind: str
    """`spurt` or `news`."""
    day: date
    minute: int
    """Minutes after 09:15 on `day` (negative before the open)."""


@dataclass(frozen=True)
class Spec:
    hypothesis: str
    run_id: str
    kind: str
    in_hours: bool
    lookback: int
    """Sessions the faded move spans (outside-hours rules)."""
    threshold: float


SPECS = (
    Spec("H-0107", "nse_spurt_query_fade_next_session", "spurt", False, 3, 0.03),
    Spec("H-0108", "nse_news_verification_fade_next_session", "news", False, 1, 0.02),
    Spec("H-0109", "nse_spurt_query_fade_same_day", "spurt", True, 0, 0.03),
    Spec("H-0110", "nse_news_verification_fade_same_day", "news", True, 0, 0.02),
)
BY_ID = {spec.hypothesis: spec for spec in SPECS}


def parse(rows: Sequence[Mapping[str, Any]], symbols: set[str]) -> list[Event]:
    out: list[Event] = []
    for row in rows:
        desc = str(row.get("desc") or "").strip()
        kind = "spurt" if desc in SPURT else "news" if desc in NEWS else None
        symbol = str(row.get("symbol") or "")
        if kind is None or symbol not in symbols:
            continue
        try:
            # NSE writes Indian time without a zone.
            when = datetime.strptime(str(row.get("exchdisstime")), "%d-%b-%Y %H:%M:%S").replace(
                tzinfo=IST
            )
        except ValueError:
            continue
        minute = (when.hour - 9) * 60 + when.minute - 15
        out.append(Event(symbol, kind, when.date(), minute))
    return sorted(out, key=lambda e: (e.day, e.minute, e.symbol))


def load_events(symbols: set[str], path: Path = EVENTS) -> list[Event]:
    """Every query in `nse_announcements` for `symbols`, cached after the first read."""
    if path.exists():
        return [
            Event(r[0], r[1], date.fromisoformat(r[2]), r[3])
            for r in json.loads(path.read_text(encoding="utf-8"))
        ]
    from eulerlab.ingest import landing_reader

    rows: list[dict[str, Any]] = []
    for name in sorted(landing_reader.available("nse_announcements", "*.json")):
        rows.extend(json.loads(landing_reader.read(name, cache=True)))
    events = parse(rows, symbols)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([[e.symbol, e.kind, e.day.isoformat(), e.minute] for e in events]),
        encoding="utf-8",
    )
    return events


def _checkpoint(minute: int) -> int:
    """The first 5-minute snapshot close at or after `minute`."""
    steps = max(0, math.ceil((minute - six.DAY_START) / six.STEP))
    return six.DAY_START + steps * six.STEP


def candidates(
    spec: Spec,
    events: Sequence[Event],
    snaps: Mapping[str, Mapping[date, six.Snap]],
    sessions: Sequence[date],
    *,
    delay: int = 0,
) -> list[tuple[date, str, five.Fill, float]]:
    """(trade day, symbol, fill, |move|) for every qualifying event, one per stock-day."""
    session_set = set(sessions)
    seen: set[tuple[date, str]] = set()
    out: list[tuple[date, str, five.Fill, float]] = []
    for event in events:
        if event.kind != spec.kind:
            continue
        if spec.in_hours:
            if not six.DAY_START <= event.minute <= LAST_IN_HOURS:
                continue
            i = bisect.bisect_left(sessions, event.day)
            if i >= len(sessions) or sessions[i] != event.day or i == 0:
                continue
            day = event.day
        else:
            if OPEN_MINUTES <= event.minute < CLOSED_AFTER and event.day in session_set:
                continue  # posted in hours: not this rule's event
            # Before the open on a session: that session. Otherwise the next one.
            if event.minute < OPEN_MINUTES:
                i = bisect.bisect_left(sessions, event.day)
            else:
                i = bisect.bisect_right(sessions, event.day)
            if i >= len(sessions) or i < max(spec.lookback, 1):
                continue
            day = sessions[i]
        if (day, event.symbol) in seen:
            continue
        own = snaps.get(event.symbol, {})
        today, before = own.get(day), own.get(sessions[i - 1])
        if today is None or before is None or today.entry < cs.MIN_PRICE:
            continue
        if spec.in_hours:
            point = _checkpoint(event.minute) + delay
            if point >= cs.EXIT:
                continue
            move = today.closes[six._k(point)] / before.last_close - 1.0
        else:
            start = own.get(sessions[i - 1 - spec.lookback])
            if start is None:
                continue
            point = six.DAY_START + delay
            move = before.last_close / start.last_close - 1.0
        if abs(move) < spec.threshold:
            continue
        direction = -1 if move > 0 else 1
        if point == six.DAY_START:
            fill: five.Fill | None = five.Fill(
                point, direction, today.entry_minute, today.entry, today.exit_minute, today.exit
            )
        else:
            fill = six._from(today, point, direction)
        if fill is None:
            continue
        seen.add((day, event.symbol))
        out.append((day, event.symbol, fill, abs(move)))
    return out


def capped(
    found: Sequence[tuple[date, str, five.Fill, float]],
) -> list[tuple[date, str, five.Fill]]:
    """At most ten a day, largest move first, then symbol."""
    by_day: dict[date, list[tuple[float, str, five.Fill]]] = defaultdict(list)
    for day, symbol, fill, size in found:
        by_day[day].append((-size, symbol, fill))
    out: list[tuple[date, str, five.Fill]] = []
    for day in sorted(by_day):
        ranked = sorted(by_day[day], key=lambda item: (item[0], item[1]))[: five.MAX_OPEN]
        out.extend((day, symbol, fill) for _, symbol, fill in ranked)
    return out


def _load() -> tuple[list[Event], dict[str, dict[date, six.Snap]], list[date]]:
    snaps, window = fo.load_snaps()
    return load_events(set(snaps)), snaps, window


def validation_run(hypothesis: str) -> IntradayRun:
    """Trades as screened and five minutes late, for the battery (ADR-139)."""
    from eulerlab.validation.intraday import IntradayRun

    spec = BY_ID[hypothesis]
    events, snaps, window = _load()

    def book(delay: int) -> list[cs.Trade]:
        fills = capped(candidates(spec, events, snaps, window, delay=delay))
        return [t for d, s, f in fills if (t := five._trade(s, d, f, f.direction, five.TRADE))]

    return IntradayRun(book(0), book(LATE), list(window), five.TRADE * five.MAX_OPEN)


def run(output: Path = OUT) -> dict[str, Any]:
    events, snaps, window = _load()
    runs = []
    for spec in SPECS:
        found = candidates(spec, events, snaps, window)
        runs.append(
            {
                "hypothesis": spec.hypothesis,
                "events": sum(1 for e in events if e.kind == spec.kind),
                "qualifying": len(found),
                **six.evaluate(spec.run_id, capped(found), window, five.TRADE * five.MAX_OPEN),
            }
        )
    result = {"research": "167", "spent_trials": 0, "runs": runs}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="nse-queries")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    for one in run(args.output)["runs"]:
        years = {y: v["total_return"] for y, v in one["net_by_year"].items()}
        print(
            f"{one['hypothesis']} {one['id']}: {one['trades']} trades of {one['qualifying']} "
            f"qualifying; {one['per_trade_bps']['gross_mean']} bps gross, "
            f"{one['per_trade_bps']['net_mean']} net; net Sharpe {one['net']['sharpe']}; {years}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
