"""What data the platform holds, up to which day, and what is missing.

The Instruments page could search instruments but could not answer "is
everything here up to today?". On 2026-10-08 the bhavcopy had landed and the
paper books still showed 7 Oct, and nothing on any page said so (T-4030).

One row per dataset: the last day held, the day it should reach by now, how
many sessions it is behind, and what fixes it. Read from files that are
already local — the NSE manifest, the derived tables' last lines, the landing
census, the paper states — so the page answers in well under a second and
never lists the bucket.

### What "should reach" means

- **nse** — the latest weekday that is not a known NSE closure, counting today
  only from 19:00 IST, when the day's files are out. Future holidays are not
  known here (T-3998), so a holiday reads as one session behind until the next
  trading day lands.
- **amfi** — mutual fund NAVs are published late in the evening: the previous
  weekday.
- **us** — the latest New York weekday, from 18:00 New York. US holidays are
  not known here, so one reads as one session behind.
- **crypto** — Binance publishes each UTC day's archive the next day: yesterday,
  UTC.
- **weekly** — FX candles come in weekly files: up to 10 days old is current.
- **info** — shown with its last day but no expectation (fundamentals refresh
  over an hour, overnight; option chain snapshots exist only in market hours).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")

LANDING = Path("data/landing")
DERIVED = Path("data/derived")
DEPLOYMENTS = Path("data/deployments")

UPDATE = "Tools → Instruments → Update all data"


@dataclass(frozen=True)
class Row:
    group: str
    name: str
    last: str
    expected: str
    behind: int
    status: str
    """ok · behind (one session) · stale (two or more) · missing · info"""
    detail: str
    fix: str
    steps: tuple[str, ...] = ()
    """The feed steps that bring this dataset up to date, in run order —
    what its own Update button runs. Empty where no button can (Kite minute
    bars need a login; fundamentals take hours)."""


# --- reading the last day cheaply ---------------------------------------------


def last_line(path: Path, *, chunk: int = 1 << 16) -> str:
    """The last non-empty line of a file, read from the end.

    The price panel is 745 MB; reading it to learn its last day would take
    seconds on every page load.
    """
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        end = handle.tell()
        buf = b""
        pos = end
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            handle.seek(pos)
            buf = handle.read(step) + buf
            lines = [x for x in buf.split(b"\n") if x.strip()]
            if len(lines) >= 2 or (pos == 0 and lines):
                return lines[-1].decode("utf-8")
    return ""


def last_day_jsonl(path: Path, field: str = "d") -> str:
    line = last_line(path)
    if not line:
        return ""
    try:
        value = json.loads(line).get(field, "")
    except json.JSONDecodeError:
        return ""
    return str(value)


_SCAN_CACHE: dict[tuple[str, str], tuple[int, dict[str, str]]] = {}


def _max_by(path: Path, group: str, value: str, *, nonempty: bool = False) -> dict[str, str]:
    """`{group value: max(value)}` across a JSONL manifest, cached by mtime."""
    if not path.exists():
        return {}
    stamp = path.stat().st_mtime_ns
    key = (str(path), f"{group}|{value}|nonempty={nonempty}")
    cached = _SCAN_CACHE.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if nonempty and int(row.get("rows", 0)) <= 0:
                continue
            g = str(row.get(group, "")) if group else ""
            v = str(row.get(value, ""))
            if v and v > out.get(g, ""):
                out[g] = v
    _SCAN_CACHE[key] = (stamp, out)
    return out


def _local_latest(tree: str, pattern: str) -> str:
    from eulerlab.ingest.manifest import latest_date

    root = LANDING / tree
    if not root.exists():
        return ""
    return latest_date(str(p.relative_to(root)) for p in root.glob(pattern))


def _census_latest(key: str) -> str:
    from eulerlab.ingest import manifest

    loaded = manifest.load()
    census = loaded.census(key) if loaded else None
    return census.latest if census else ""


# --- what each cadence should have reached -------------------------------------


def _weekday_back(day: date, closed: frozenset[date]) -> date:
    while day.weekday() >= 5 or day in closed:
        day -= timedelta(days=1)
    return day


# ASSUMPTION: A-051 — the cut-off times below are observed, not published.
def expected_nse(now: datetime, closed: frozenset[date]) -> date:
    ist = now.astimezone(IST)
    day = ist.date() if ist.hour >= 19 else ist.date() - timedelta(days=1)
    return _weekday_back(day, closed)


def expected_amfi(now: datetime, closed: frozenset[date]) -> date:
    return _weekday_back(now.astimezone(IST).date() - timedelta(days=1), frozenset())


def expected_us(now: datetime, closed: frozenset[date]) -> date:
    ny = now.astimezone(NEW_YORK)
    day = ny.date() if ny.hour >= 18 else ny.date() - timedelta(days=1)
    return _weekday_back(day, frozenset())


def expected_crypto(now: datetime, closed: frozenset[date]) -> date:
    return now.astimezone(UTC).date() - timedelta(days=1)


EXPECTED: dict[str, Callable[[datetime, frozenset[date]], date]] = {
    "nse": expected_nse,
    "amfi": expected_amfi,
    "us": expected_us,
    "crypto": expected_crypto,
}


def sessions_behind(last: date, expected: date, cadence: str, closed: frozenset[date]) -> int:
    """Sessions in (last, expected] for this cadence."""
    if last >= expected:
        return 0
    count, day = 0, last
    while day < expected:
        day += timedelta(days=1)
        if cadence == "crypto" or (day.weekday() < 5 and not (cadence == "nse" and day in closed)):
            count += 1
    return count


def judge(*, steps: tuple[str, ...] = (), **kw: Any) -> Row:
    """One row: compare `last` against what `cadence` should have reached."""
    return replace(_grade(**kw), steps=steps)


def _grade(
    *,
    group: str,
    name: str,
    last: str,
    cadence: str,
    now: datetime,
    closed: frozenset[date],
    detail: str = "",
    fix: str = UPDATE,
) -> Row:
    if not last:
        return Row(group, name, "", "", 0, "missing", detail or "nothing held", fix)
    if cadence == "info":
        return Row(group, name, last, "", 0, "info", detail, fix)
    last_day = _as_day(last)
    if cadence == "weekly":
        age = (now.astimezone(UTC).date() - last_day).days
        status = "ok" if age <= 10 else "behind" if age <= 17 else "stale"
        return Row(group, name, last, "within 10 days", 0, status, detail, fix)
    expected = EXPECTED[cadence](now, closed)
    behind = sessions_behind(last_day, expected, cadence, closed)
    status = "ok" if behind == 0 else "behind" if behind == 1 else "stale"
    return Row(group, name, last, expected.isoformat(), behind, status, detail, fix)


def _as_day(text: str) -> date:
    """A `YYYY-MM-DD`, or a `YYYY-MM` month read as its last day held."""
    if len(text) == 7:
        first = date.fromisoformat(f"{text}-01")
        nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt - timedelta(days=1)
    return date.fromisoformat(text[:10])


def nse_closures(path: Path = DERIVED / "nse_calendar.json") -> frozenset[date]:
    if not path.exists():
        return frozenset()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return frozenset()
    return frozenset(date.fromisoformat(d) for d in raw.get("holidays", []))


# --- the table -----------------------------------------------------------------

_EOD = "NSE end-of-day"
_FILES = "NSE index closes and delivery"
PAPER_STEPS: tuple[str, ...] = (_EOD, "price panel", "paper books")

STEPS_FOR: dict[str, tuple[str, ...]] = {
    "Cash bhavcopy": (_EOD,),
    "F&O bhavcopy": (_EOD,),
    "Participant OI": ("participant OI",),
    "Index closes (incl. VIX)": (_FILES,),
    "Delivery positions": (_FILES,),
    "Price panel": (_EOD, "price panel"),
    "Index history": (_FILES, "market history"),
    "Delivery table": (_FILES, "market history"),
    "Nifty futures": (_EOD, "market history"),
    "Nifty options": (_EOD, "Nifty options"),
    "US daily panel": ("US bars and actions", "US panel"),
    "Crypto 1-minute": ("crypto gap",),
    "FX 1-minute": ("FX",),
    "Mutual fund NAVs": ("mutual fund NAVs",),
    "Option chain snapshots": ("option chain",),
    "India minute bars (Kite)": ("India minute bars",),
    "MCX iCOMDEX minute bars (Kite)": ("MCX index minute bars",),
}
"""Each dataset's own Update button: the fetch it derives from, then the build.
Every name must be a `daily_feed.STEPS` name (tests/test_data_pipeline.py)."""


def _paper_rows(now: datetime, closed: frozenset[date]) -> Iterable[Row]:
    if not DEPLOYMENTS.exists():
        return
    for folder in sorted(DEPLOYMENTS.iterdir()):
        spec_path, state_path = folder / "deployment.json", folder / "state.json"
        if not spec_path.exists():
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        if spec.get("status") != "active":
            continue
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        row = judge(
            group="Paper trading",
            name=f"{spec.get('strategy_id')} · ₹{float(spec.get('capital', 0)):,.0f}",
            last=str(state.get("traded_through") or ""),
            cadence="nse",
            now=now,
            closed=closed,
            detail=f"{state.get('status', 'not run')} — {spec.get('id')}",
            steps=PAPER_STEPS,
        )
        # A deployment younger than two sessions has nothing to trade yet; that
        # is waiting, not stale.
        if state.get("status") == "waiting":
            row = Row(**{**asdict(row), "status": "info", "detail": str(state.get("reason"))})
        yield row


def table(now: datetime | None = None) -> list[Row]:
    now = now or datetime.now(UTC)
    closed = nse_closures()
    nse = _max_by(LANDING / "nse" / "manifest.jsonl", "segment", "trade_date")
    rows: list[Row] = []

    def add(group: str, name: str, last: str, cadence: str, **kw: Any) -> None:
        rows.append(
            judge(
                group=group,
                name=name,
                last=last,
                cadence=cadence,
                now=now,
                closed=closed,
                steps=STEPS_FOR.get(name, ()),
                **kw,
            )
        )

    landed = "NSE files (landed)"
    add(landed, "Cash bhavcopy", nse.get("cm", ""), "nse", detail="every NSE equity, daily")
    add(landed, "F&O bhavcopy", nse.get("fo", ""), "nse", detail="every derivative, daily")
    add(landed, "Participant OI", nse.get("participant_oi", ""), "nse")
    add(landed, "Index closes (incl. VIX)", nse.get("indices", ""), "nse")
    add(landed, "Delivery positions", nse.get("delivery", ""), "nse")

    built = "Built for research and trading"
    add(
        built,
        "Price panel",
        last_day_jsonl(DERIVED / "price_panel.jsonl"),
        "nse",
        detail="what backtests and paper trading read",
    )
    add(built, "Index history", last_day_jsonl(DERIVED / "index_history.jsonl"), "nse")
    add(built, "Delivery table", last_day_jsonl(DERIVED / "delivery.jsonl"), "nse")
    add(built, "Nifty futures", last_day_jsonl(DERIVED / "nifty_futures.jsonl"), "nse")
    add(built, "Nifty options", last_day_jsonl(DERIVED / "nifty_options.jsonl"), "nse")
    add(built, "US daily panel", last_day_jsonl(DERIVED / "us_panel.jsonl"), "us")

    rows.extend(_paper_rows(now, closed))

    other = "Other markets (landed)"
    add(
        other,
        "Crypto 1-minute",
        max(_census_latest("crypto"), _local_latest("crypto", "*/*.jsonl.gz")),
        "crypto",
    )
    add(
        other,
        "FX 1-minute",
        max(_census_latest("fx"), _local_latest("fx", "*/*/*.jsonl.gz")),
        "weekly",
    )
    add(
        other,
        "Mutual fund NAVs",
        max(_census_latest("mf/navall"), _local_latest("mf", "navall/*.jsonl.gz")),
        "amfi",
    )

    slow = "Not in the button"
    kite = _max_by(LANDING / "kite_minute" / "manifest.jsonl", "", "end").get("", "")
    add(
        "Needs a Kite login",
        "India minute bars (Kite)",
        kite,
        "nse",
        detail="needs a Kite token minted today: log in to Kite above",
        fix="Log in to Kite on this page, then Update",
    )
    mcx_indexes = _max_by(
        LANDING / "mcx_indices" / "manifest.jsonl", "symbol", "end", nonempty=True
    )
    mcx_last = max(mcx_indexes.values(), default="")
    add(
        "Needs a Kite login",
        "MCX iCOMDEX minute bars (Kite)",
        mcx_last,
        "nse",
        detail=(
            f"{len(mcx_indexes)} index series landed; Kite history is partial and the "
            "full five-year window was queried, including empty history ranges"
        ),
        fix="Log in to Kite on this page, then Update",
    )
    funda = _max_by(LANDING / "fundamentals" / "manifest.jsonl", "", "fetch_date").get("", "")
    add(
        slow,
        "Fundamentals",
        funda,
        "info",
        detail="walks every symbol for hours; runs at the end of make daily",
        fix="make daily",
    )
    chain = _local_latest("option_chain", "*/*")
    add(
        slow,
        "Option chain snapshots",
        chain,
        "info",
        detail="bid/ask exists only in market hours; the button takes one if open",
    )
    return rows


def summary(rows: list[Row]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        out[row.status] = out.get(row.status, 0) + 1
    return out


def main() -> int:
    """`make coverage`: the Instruments table, in a terminal."""
    rows = table()
    group = ""
    for row in rows:
        if row.group != group:
            group = row.group
            print(f"\n{group}")
        fix = f"  → {row.fix}" if row.status not in ("ok", "info") else ""
        print(f"  {row.status:8s} {row.name:40s} {row.last or '—':11s} {row.expected:14s}{fix}")
    counts = summary(rows)
    print("\n" + " · ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    return 1 if counts.get("stale") or counts.get("missing") else 0


if __name__ == "__main__":
    raise SystemExit(main())
