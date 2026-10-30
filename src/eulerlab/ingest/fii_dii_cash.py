"""`make fii-dii` — FII/DII provisional cash-market flows, captured from NSE daily.

NSE publishes, each evening, what foreign (FII/FPI) and domestic (DII)
institutions bought and sold in the cash market that day, in ₹ crore. It
serves **the latest day only**: `fiidiiTradeReact` has no range parameter, and
the `?date=` it accepts is silently ignored (research 004). So this source is
capture-only. A day not captured on its evening, or before NSE moves on to
the next session, is gone from NSE for good.

The operator asked for the data shown on scanx.trade's FII/DII page. That page
could not be read from here and its terms were not read, so this lands NSE's
own figures, which aggregators such as scanx republish (research 126, ADR-088).

Three rules, from what this endpoint has already taught us:

1. **The date comes from the payload, never from the request.** The file is
   landed under the day NSE says the numbers are for. A request on a holiday
   or a weekend returns the last session's figures, which then skip as held.
2. **A held day is skipped by the manifest, not by the file on disk.** Landed
   files are moved to B2 and pruned locally, and the request has to be made
   anyway to learn the date. Checking the manifest keeps a re-run from
   landing the same day twice.
3. **Plausible garbage is refused.** Both FII and DII rows must be present,
   for the same day, and each row's net must equal buy minus sell.

Each landed day is also appended to `data/derived/fii_dii_cash.jsonl` with its
event time (the trade date) and knowledge time (when it was landed), which is
what the dashboard and any research reader use. `rows(as_of=...)` cannot
return a row known after `as_of`.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.ingest.fetch import Fetcher, FetchPolicy, Outcome, UrllibTransport
from eulerlab.ingest.holidays import parse_nse_date
from eulerlab.ingest.landing import Landing

URL = "https://www.nseindia.com/api/fiidiiTradeReact"
TREE = "fii_dii"
SEGMENT = "cash"
DEFAULT_LANDING = Path("data/landing") / TREE
DERIVED = Path("data/derived/fii_dii_cash.jsonl")
IST = ZoneInfo("Asia/Kolkata")

TOLERANCE_CRORE = 0.05
"""Net must equal buy minus sell to within this. NSE rounds each figure to two
decimals, so a correct row is off by at most 0.01; 0.05 leaves room without
letting a wrong column through."""


@dataclass(frozen=True)
class Flow:
    """One group's cash-market trades for a day, ₹ crore."""

    buy: float
    sell: float
    net: float


@dataclass(frozen=True)
class FlowDay:
    trade_date: date
    fii: Flow
    dii: Flow


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _group(category: str) -> str | None:
    """'FII/FPI **' → FII, 'DII **' → DII. Anything else is not ours."""
    text = category.upper()
    if text.lstrip().startswith("DII"):
        return "DII"
    if "FII" in text or "FPI" in text:
        return "FII"
    return None


def parse(payload: bytes) -> FlowDay | None:
    """NSE's JSON, or None when it is not one day's FII and DII rows.

    The response is a list of objects with `category`, `date` (DD-Mon-YYYY),
    `buyValue`, `sellValue` and `netValue`, confirmed by the first live run on
    2026-10-30 (A-070, tests/fixtures/fii_dii).
    """
    try:
        raw = json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list):
        return None
    found: dict[str, tuple[date, Flow]] = {}
    for row in raw:
        if not isinstance(row, dict):
            continue
        group = _group(str(row.get("category") or ""))
        day = parse_nse_date(str(row.get("date") or ""))
        buy, sell, net = (_number(row.get(k)) for k in ("buyValue", "sellValue", "netValue"))
        if group is None or day is None or buy is None or sell is None or net is None:
            continue
        if buy < 0 or sell < 0 or abs(buy - sell - net) > TOLERANCE_CRORE:
            return None
        if group in found:
            return None  # two FII rows: not the report we know
        found[group] = (day, Flow(buy=buy, sell=sell, net=net))
    if set(found) != {"FII", "DII"}:
        return None
    (fii_day, fii), (dii_day, dii) = found["FII"], found["DII"]
    if fii_day != dii_day:
        return None
    return FlowDay(trade_date=fii_day, fii=fii, dii=dii)


# --- the derived table -------------------------------------------------------------


def to_row(day: FlowDay, knowledge_time: str, *, source: str = "nse") -> dict[str, Any]:
    """`source` is `nse` for this module's capture, or the aggregator a backfilled
    row came from (`fii_dii_history`). A row without it is NSE's."""
    return {
        "day": day.trade_date.isoformat(),
        "source": source,
        "event_time": datetime.combine(day.trade_date, time(15, 30), IST).isoformat(),
        "knowledge_time": knowledge_time,
        "fii_buy": day.fii.buy,
        "fii_sell": day.fii.sell,
        "fii_net": day.fii.net,
        "dii_buy": day.dii.buy,
        "dii_sell": day.dii.sell,
        "dii_net": day.dii.net,
    }


def rows(path: Path = DERIVED, *, as_of: datetime | None = None) -> list[dict[str, Any]]:
    """Every stored day, oldest first, known at or before `as_of` (default: now).

    One row per day: if the table ever holds a day twice, the first known wins,
    because that is what a reader at the time would have seen.
    """
    if not path.exists():
        return []
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None:
        msg = "as_of must carry a time zone"
        raise ValueError(msg)
    seen: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            known = datetime.fromisoformat(str(row["knowledge_time"]))
        except (ValueError, KeyError, TypeError):
            continue
        if known > cutoff:
            continue
        held = seen.get(str(row["day"]))
        if held is None or datetime.fromisoformat(held["knowledge_time"]) > known:
            seen[str(row["day"])] = row
    return [seen[d] for d in sorted(seen)]


def append(day: FlowDay, knowledge_time: str, path: Path = DERIVED) -> bool:
    """Add one day to the table. False when the day is already there."""
    if any(r["day"] == day.trade_date.isoformat() for r in rows(path, as_of=_far_future())):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(to_row(day, knowledge_time), sort_keys=True) + "\n")
    return True


def _far_future() -> datetime:
    return datetime(9999, 1, 1, tzinfo=UTC)


def rebuild(
    landing: Landing,
    read: Callable[[str], bytes],
    path: Path = DERIVED,
) -> int:
    """Write the table again from every landed file. Returns the days written.

    `read` takes a landing-relative path (`fii_dii/cash/...`), so a file pruned
    to B2 is read from there. NSE's days come first; landed aggregator pages
    fill the days NSE never served. The output is sorted, so a rebuild of the same
    files is byte-identical.
    """
    out: dict[str, dict[str, Any]] = {}
    for (day, segment), entry in landing.entries().items():
        if segment != SEGMENT or day in out:
            continue
        parsed = parse(read(f"{TREE}/{entry.path}"))
        if parsed is not None:
            out[day] = to_row(parsed, entry.knowledge_time)
    # Backfilled days fill only what NSE's own capture does not hold (ADR-089).
    from eulerlab.ingest import fii_dii_history

    for day, row in fii_dii_history.history_rows(
        landing, read, today=datetime.now(IST).date(), known=fii_dii_history.trading_days()
    ).items():
        out.setdefault(day, row)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(
        "".join(json.dumps(out[d], sort_keys=True) + "\n" for d in sorted(out)), encoding="utf-8"
    )
    tmp.replace(path)
    return len(out)


# --- capture -----------------------------------------------------------------------


def capture(fetcher: Fetcher, landing: Landing, *, today: date, derived: Path = DERIVED) -> str:
    """One request. Returns downloaded, skipped, absent, failed or malformed."""
    result = fetcher.get(URL)
    if result.outcome is Outcome.ABSENT:
        return "absent"
    if result.outcome is Outcome.FAILED or result.payload is None:
        return "failed"
    parsed = parse(result.payload)
    if parsed is None or parsed.trade_date > today:
        return "malformed"
    held = landing.entries().get((parsed.trade_date.isoformat(), SEGMENT))
    if held is not None:
        # Landed before; make sure the table has it too (a crash between the
        # two writes, or a table deleted by hand).
        append(parsed, held.knowledge_time, derived)
        return "skipped"
    entry = landing.write(
        trade_date=parsed.trade_date,
        segment=SEGMENT,
        file_format="json",
        url=URL,
        payload=result.payload,
        rows=2,
        inner_name=f"fiidiiTradeReact_{parsed.trade_date.isoformat()}.json",
        suffix="json",
    )
    append(parsed, entry.knowledge_time, derived)
    return "downloaded"


# --- what the dashboard shows ------------------------------------------------------


def _sum(values: Iterable[float]) -> float:
    return round(sum(values), 2)


def streak(nets: Sequence[float]) -> int:
    """Sessions in a row the latest sign has held: +3 three buying days, -2 two selling."""
    if not nets or nets[-1] == 0:
        return 0
    sign = 1 if nets[-1] > 0 else -1
    count = 0
    for value in reversed(nets):
        if value * sign <= 0:
            break
        count += 1
    return sign * count


def _sources(held: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Days held per source: `nse` for the capture, an aggregator for a backfill."""
    out: dict[str, int] = {}
    for row in held:
        name = str(row.get("source", "nse"))
        out[name] = out.get(name, 0) + 1
    return dict(sorted(out.items()))


def summary(held: Sequence[Mapping[str, Any]], *, window: int = 60) -> dict[str, Any]:
    """The dashboard's FII/DII cash-flow section, from `rows()`."""
    if not held:
        return {
            "available": False,
            "reason": "no day captured yet: `make fii-dii` captures it on a trading day's evening",
        }
    last = held[-1]
    month = str(last["day"])[:7]
    months: dict[str, dict[str, float]] = {}
    for row in held:
        bucket = months.setdefault(str(row["day"])[:7], {"fii": 0.0, "dii": 0.0, "days": 0})
        bucket["fii"] += float(row["fii_net"])
        bucket["dii"] += float(row["dii_net"])
        bucket["days"] += 1
    recent = held[-window:]

    def group(prefix: str) -> dict[str, Any]:
        nets = [float(r[f"{prefix}_net"]) for r in held]
        return {
            "buy": last[f"{prefix}_buy"],
            "sell": last[f"{prefix}_sell"],
            "net": last[f"{prefix}_net"],
            "net_5d": _sum(nets[-5:]),
            "net_month": _sum(float(r[f"{prefix}_net"]) for r in held if r["day"][:7] == month),
            "streak": streak(nets),
        }

    return {
        "available": True,
        "as_of": last["day"],
        "known_at": last["knowledge_time"],
        "days_held": len(held),
        "first_day": held[0]["day"],
        "fii": group("fii"),
        "dii": group("dii"),
        "series": {
            "days": [r["day"] for r in recent],
            "fii": [r["fii_net"] for r in recent],
            "dii": [r["dii_net"] for r in recent],
        },
        "months": [
            {
                "month": m,
                "fii": round(v["fii"], 2),
                "dii": round(v["dii"], 2),
                "days": int(v["days"]),
            }
            for m, v in sorted(months.items())[-12:]
        ],
        "sources": _sources(held),
        "note": "NSE's provisional figures for the cash market, ₹ crore, published each evening "
        "for that day only. Days before NSE capture began are backfilled from Trendlyne's "
        "republication (0.1 crore precision, ADR-089). FII includes FPI. They are revised later "
        "by NSDL and are context, not a signal: nothing built on them has passed the gate.",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fii-dii")
    parser.add_argument("--landing", type=Path, default=DEFAULT_LANDING)
    parser.add_argument("--derived", type=Path, default=DERIVED)
    parser.add_argument(
        "--rebuild", action="store_true", help="rewrite the table from the landed files"
    )
    args = parser.parse_args(argv)
    landing = Landing(args.landing)

    if args.rebuild:
        from eulerlab.ingest import landing_reader

        def read(relative: str) -> bytes:
            local = args.landing.parent / relative
            return local.read_bytes() if local.exists() else landing_reader.read(relative)

        print(f"fii-dii: rebuilt {rebuild(landing, read, args.derived)} day(s)")
        return 0

    transport = UrllibTransport()
    transport.establish_session()
    fetcher = Fetcher(transport, FetchPolicy())
    outcome = capture(fetcher, landing, today=datetime.now(IST).date(), derived=args.derived)
    held = rows(args.derived)
    print(
        f"fii-dii: {outcome}  ({len(held)} day(s) held, latest {held[-1]['day'] if held else '-'})"
    )
    print(f"  done: {{'{outcome}': 1}}")
    # Malformed is a failure too: either NSE changed the report or served
    # something else, and both need a person before the day is lost.
    return 1 if outcome in {"failed", "malformed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
