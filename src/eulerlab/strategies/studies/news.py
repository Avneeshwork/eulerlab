"""Five intraday news rules from NSE corporate announcements (research 160).

Pre-registered as H-0072 to H-0076 before any run. Events are every filing in
`data/landing/nse_announcements` (all categories, 2021-07 to 2024-12), timed by
NSE's dissemination time. Kite minute bars of F&O stocks to 2024-11-29; ₹1
lakh a trade, 1x, at most ten a day, earliest disclosure first; cash-intraday
charges plus 2 bps a side.

- **H-0072 press release, H-0073 acquisition or merger, H-0074 credit
  rating.** Jiang, Li and Wang (2021): disclosed 09:20-14:30, a 1% move over
  the next five minutes is followed from the next open to 15:10 (the same
  mechanics as `earnings_reaction_screen.mark`).
- **H-0075 dividend.** Disclosed 09:20-14:30: buy the next minute, sell 15:10.
- **H-0076 buyback.** In hours: buy the next minute; outside hours: buy the
  next session's 09:20 open; sell 15:10.

`make news-intraday` writes `data/derived/news_intraday.json`.
"""

from __future__ import annotations

import argparse
import importlib
import json
import pickle
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip
from eulerlab.paths import data_path
from eulerlab.strategies.studies import cash_five as five
from eulerlab.strategies.studies import earnings_reaction as earnings

OUT = data_path("derived/news_intraday.json")
PARTS = data_path("derived/news_intraday_parts")
EVENTS = PARTS / "events.pkl"
BATCH = 40
CATEGORIES = {
    "Press Release": "press",
    "Acquisition": "mna",
    "Amalgamation/Merger": "mna",
    "Credit Rating": "rating",
    "Dividend": "dividend",
    "Buyback": "buyback",
}
FOLLOW = ("press", "mna", "rating")
RULES = (
    ("H-0072", "press", "nse_press_release_follow"),
    ("H-0073", "mna", "nse_acquisition_follow"),
    ("H-0074", "rating", "nse_credit_rating_follow"),
    ("H-0075", "dividend", "nse_dividend_day"),
    ("H-0076", "buyback", "nse_buyback_day"),
)
FIRST, LAST = earnings.FIRST, earnings.LAST
"""09:20 to 14:30, as minutes after 09:15."""
PRE_OPEN = -1
IST = ZoneInfo("Asia/Kolkata")
"""NSE's dissemination times are Indian time, written without a zone."""
DAY_START = 5

Events = dict[str, dict[str, list[datetime]]]
"""{symbol: {rule: disclosure times}}."""


def parse_time(row: Mapping[str, Any]) -> datetime | None:
    for key in ("exchdisstime", "an_dt", "sort_date"):
        text = str(row.get(key) or "").strip()
        for pattern in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, pattern).replace(tzinfo=IST)
            except ValueError:
                continue
    return None


def load_events(rows: Sequence[Mapping[str, Any]]) -> Events:
    out: Events = defaultdict(lambda: defaultdict(list))
    for row in rows:
        rule = CATEGORIES.get(str(row.get("desc") or "").strip())
        when = parse_time(row)
        if rule is None or when is None:
            continue
        out[str(row.get("symbol") or "")][rule].append(when)
    return {s: {r: sorted(v) for r, v in rules.items()} for s, rules in out.items()}


def _minute(when: datetime) -> int:
    return (when.hour - 9) * 60 + when.minute - 15


def _hold(day: ip.Day, start: int, minute: int) -> five.Fill | None:
    entry, leave = day.fill_at(start), day.fill_at(cs.EXIT)
    if entry is None or leave is None or entry[0] >= leave[0]:
        return None
    return five.Fill(minute, 1, entry[0], entry[1], leave[0], leave[1])


def marks_for(
    days: Sequence[ip.Day], mine: Mapping[str, list[datetime]]
) -> dict[str, dict[date, five.Fill]]:
    """Each rule's first trade a session for one stock."""
    by_day = {d.day: d for d in days}
    sessions = sorted(by_day)
    out: dict[str, dict[date, five.Fill]] = {rule: {} for _, rule, _ in RULES}
    for rule, times in mine.items():
        for when in times:
            minute = _minute(when)
            day = by_day.get(when.date())
            in_hours = day is not None and FIRST <= minute <= LAST
            if in_hours and day is not None and when.date() not in out[rule]:
                if day.close[minute - 1] < cs.MIN_PRICE:
                    continue
                fill: five.Fill | None
                if rule in FOLLOW:
                    found = earnings.mark(day, minute)
                    fill = (
                        five.Fill(
                            minute,
                            1 if found.reaction > 0 else -1,
                            found.entry_minute,
                            found.entry,
                            found.exit_minute,
                            found.exit,
                        )
                        if found is not None
                        else None
                    )
                else:
                    fill = _hold(day, minute + 1, minute)
                if fill is not None:
                    out[rule][when.date()] = fill
            elif rule == "buyback" and (day is None or minute < 0 or minute >= ip.MINUTES):
                # Outside hours: the first session that opens after the filing.
                after = [
                    s for s in sessions if s > when.date() or (s == when.date() and minute < 0)
                ]
                if after and after[0] not in out[rule]:
                    target = by_day[after[0]]
                    fill = _hold(target, DAY_START, PRE_OPEN)
                    if fill is not None:
                        out[rule][after[0]] = fill
    return out


def extract_batch(symbols: list[str], part: Path) -> None:
    events: Events = pickle.loads(EVENTS.read_bytes())

    def extract(symbol: str, days: Sequence[ip.Day]) -> dict[str, dict[date, five.Fill]]:
        return marks_for(days, events.get(symbol, {}))

    found, sessions = cs.scan(symbols, {"marks": extract})
    part.parent.mkdir(parents=True, exist_ok=True)
    tmp = part.with_suffix(".partial")
    tmp.write_bytes(pickle.dumps({"marks": found["marks"], "sessions": sessions}))
    tmp.replace(part)


def evaluate(
    run_id: str, marks: Mapping[str, Mapping[date, five.Fill]], sessions: Sequence[date]
) -> dict[str, Any]:
    by_day: dict[date, list[tuple[int, str, five.Fill]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, fill in days.items():
            by_day[day].append((fill.minute, symbol, fill))
    trades = []
    for day, found in by_day.items():
        found.sort(key=lambda item: (item[0], item[1]))
        for _, symbol, fill in found[: five.MAX_OPEN]:
            trade = five._trade(symbol, day, fill, fill.direction, five.TRADE)
            if trade:
                trades.append(trade)
    run = cs.report(
        run_id,
        trades,
        sessions,
        params={"slippage_bps_per_side": cs.SLIPPAGE_BPS},
        capital=five.TRADE * five.MAX_OPEN,
    )
    run["event_days"] = len(by_day)
    return five._halves(run)


def run(output: Path = OUT) -> dict[str, Any]:
    from eulerlab.ingest import landing_reader

    if not EVENTS.exists():
        rows: list[dict[str, Any]] = []
        for name in sorted(
            landing_reader.available("nse_announcements", "*.json", allow_cloud=True)
        ):
            rows.extend(json.loads(landing_reader.read(name, cache=False)))
        EVENTS.parent.mkdir(parents=True, exist_ok=True)
        EVENTS.write_bytes(pickle.dumps(load_events(rows)))
    symbols = cs.universe()
    batches = [symbols[i : i + BATCH] for i in range(0, len(symbols), BATCH)]
    for number, batch in enumerate(batches):
        part = PARTS / f"{number:03d}.pkl"
        if part.exists():
            continue
        command = [sys.executable, "-m", "eulerlab.strategies.studies.news", "--part", str(part)]
        subprocess.run([*command, "--batch", *batch], check=True)
        print(f"  batch {number + 1}/{len(batches)} done", file=sys.stderr, flush=True)
    marks: dict[str, dict[str, Any]] = {rule: {} for _, rule, _ in RULES}
    sessions: set[date] = set()
    for number in range(len(batches)):
        loaded = pickle.loads((PARTS / f"{number:03d}.pkl").read_bytes())
        sessions.update(loaded["sessions"])
        for symbol, found in loaded["marks"].items():
            for rule in marks:
                marks[rule][symbol] = found[rule]
    window = sorted(d for d in sessions if d <= cs.DATA_END)
    runs = [{"hypothesis": h, **evaluate(run_id, marks[rule], window)} for h, rule, run_id in RULES]
    result = {
        "research": "docs/RESEARCH/160-five-news-rules.md",
        "universe": len(symbols),
        "spent_trials": 0,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="news-intraday")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--batch", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--part", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.batch:
        # Through the module, not `__main__`, so the pickled classes can be read by others.
        importlib.import_module("eulerlab.strategies.studies.news").extract_batch(
            args.batch, args.part
        )
        return 0
    result = run(args.output)
    for one in result["runs"]:
        print(
            f"{one['hypothesis']} {one['id']}: {one['trades']} trades on {one['event_days']} days; "
            f"{one['per_trade_bps']['gross_mean']} bps gross, "
            f"{one['per_trade_bps']['net_mean']} net a trade; net Sharpe {one['net']['sharpe']}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
